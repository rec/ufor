"""Shared portable modulation cases, independent of enge and generator execution."""

import json
import math
from importlib.resources import files
from pathlib import Path

import pytest
import tomlkit
from pydantic import TypeAdapter

from ufor import modulation, modulation_contract
from ufor.base import Model
from ufor.samples import processing
from ufor.samples.controls import ControlDeclaration

MODELS: dict[str, type[Model]] = {
    'modulation': modulation.Modulation,
    'parameter': modulation.Parameter,
    'source': modulation.Source,
    'route': modulation.Route,
    'source_value': modulation.SourceValue,
    'control': ControlDeclaration,
    'event_binding': processing.EventBinding,
    'control_binding': processing.ControlBinding,
    'generator_binding': processing.GeneratorBinding,
    'follower_binding': processing.FollowerBinding,
}
DATA = json.loads(
    (Path(__file__).parents[1] / 'conformance/modulation.json').read_bytes()
)
CONTEXT = {'portable': True}


def decode(model: str, value: object) -> Model:
    if model == 'binding':
        return TypeAdapter(processing.Binding).validate_python(value, context=CONTEXT)
    return MODELS[model].model_validate(value, context=CONTEXT)


def same(actual: object, expected: object, exact: bool = False) -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and actual.keys() == expected.keys()
        for key, value in expected.items():
            same(actual[key], value, exact)
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected)
        for a, e in zip(actual, expected, strict=True):
            same(a, e, exact)
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert isinstance(actual, (int, float)) and not isinstance(actual, bool)
        assert (
            actual == expected
            if exact
            else actual
            == pytest.approx(
                expected, rel=DATA['relative_tolerance'], abs=DATA['absolute_tolerance']
            )
        )
    else:
        assert actual == expected


@pytest.mark.parametrize('case', DATA['definitions'], ids=lambda c: c['id'])
def test_definitions_and_interchange(case: dict[str, object]) -> None:
    model = str(case['model'])
    if case.get('rejected'):
        with pytest.raises(ValueError):
            decode(model, case['input'])
        return
    value = decode(model, case['input'])
    normalized = value.model_dump(mode='json')
    if 'normalized' in case:
        same(normalized, case['normalized'])
    assert decode(model, json.loads(value.model_dump_json())) == value
    text = tomlkit.dumps(value.model_dump(mode='json', exclude_none=True))
    assert decode(model, tomlkit.parse(text).unwrap()) == value


@pytest.mark.parametrize('case', DATA['maps'], ids=lambda c: c['id'])
def test_mapping_boundaries_and_errors(case: dict[str, object]) -> None:
    route = modulation.Route.model_validate(case['route'], context=CONTEXT)
    for query in case['queries']:
        value = float(query['value'])
        if 'error' in query:
            with pytest.raises(ValueError, match='f64'):
                modulation.map_value(route, value)
        else:
            same(modulation.map_value(route, value), query['expected'])


@pytest.mark.parametrize('case', DATA['evaluations'], ids=lambda c: c['id'])
def test_scalar_combination_and_route_permutations(case: dict[str, object]) -> None:
    definition = modulation.Modulation.model_validate(case['input'], context=CONTEXT)
    values = TypeAdapter(dict[str, modulation.SourceValue]).validate_python(
        case['values'], context=CONTEXT
    )
    bases = TypeAdapter(list[modulation.ParameterValue]).validate_python(
        case.get('base_values', []), context=CONTEXT
    )
    for routes in (definition.routes, list(reversed(definition.routes))):
        copy = modulation.Modulation(
            parameters=definition.parameters, sources=definition.sources, routes=routes
        )
        if 'error' in case:
            message = 'f64' if case['error'] == 'arithmetic-range' else None
            with pytest.raises(ValueError, match=message):
                modulation.evaluate(copy, values, bases)
        else:
            actual = [
                v.model_dump(mode='json')
                for v in modulation.evaluate(copy, values, bases)
            ]
            same(actual, case['expected'], bool(case.get('exact_result')))


@pytest.mark.parametrize('case', DATA['identifiers'], ids=lambda c: c['value'])
def test_pinned_identifiers(case: dict[str, object]) -> None:
    adapter = TypeAdapter(modulation_contract.Identifier)
    if case['valid']:
        assert adapter.validate_python(case['value'], context=CONTEXT) == case['value']
    else:
        with pytest.raises(ValueError):
            adapter.validate_python(case['value'], context=CONTEXT)


@pytest.mark.parametrize('case', DATA['quantities'])
def test_scalar_quantities(case: dict[str, object]) -> None:
    if case.get('rejected'):
        with pytest.raises(ValueError):
            modulation_contract.scalar_quantity(case['text'], str(case['unit']))
    else:
        actual = modulation_contract.scalar_quantity(case['text'], str(case['unit']))
        if 0 < abs(case['expected']) < 1e-12:
            assert actual == pytest.approx(case['expected'], abs=0, rel=1e-12)
        else:
            same(actual, case['expected'])
        if case.get('negative_zero'):
            assert math.copysign(1, actual) == -1


@pytest.mark.parametrize('case', DATA['local_bindings'], ids=lambda c: c['id'])
def test_local_binding_validation_reports_unresolved_context(
    case: dict[str, object],
) -> None:
    definition = modulation.Modulation.model_validate(case['input'], context=CONTEXT)
    bindings = TypeAdapter(list[processing.Binding]).validate_python(
        case['bindings'], context=CONTEXT
    )
    controls = TypeAdapter(dict[str, ControlDeclaration]).validate_python(
        case['controls'], context=CONTEXT
    )
    if 'error' in case:
        with pytest.raises(ValueError):
            processing.validate_local_bindings(definition, bindings, controls)
    else:
        actual = processing.validate_local_bindings(definition, bindings, controls)
        same([v.model_dump(mode='json') for v in actual], case['unresolved'])


@pytest.mark.parametrize(
    'case', DATA['budgets'], ids=lambda c: f'{c["kind"]}-{c["count"]}'
)
def test_preparation_budgets(case: dict[str, object]) -> None:
    if case['rejected']:
        with pytest.raises(ValueError):
            prepare(str(case['kind']), int(case['count']))
    else:
        prepare(str(case['kind']), int(case['count']))


def prepare(kind: str, count: int) -> None:
    if kind == 'parameters':
        modulation.Modulation.model_validate(
            {
                'parameters': [
                    {
                        'target': {'name': f'p{i}', 'parameter': 'x'},
                        'unit': 'ratio',
                        'scope': 'voice',
                        'minimum': 0,
                        'maximum': 1,
                        'default': 0,
                    }
                    for i in range(count)
                ]
            },
            context=CONTEXT,
        )
    elif kind == 'points':
        modulation.Route.model_validate(
            {
                'name': 'r',
                'source': 'x',
                'target': {'name': 'a', 'parameter': 'x'},
                'operation': 'add',
                'unit': 'ratio',
                'points': [{'input': i, 'amount': 0} for i in range(count)],
            },
            context=CONTEXT,
        )
    elif kind == 'aggregate':
        modulation.Modulation.model_validate(
            {
                'parameters': [
                    {
                        'target': {'name': f'p{i}', 'parameter': 'x'},
                        'unit': 'ratio',
                        'scope': 'voice',
                        'minimum': 0,
                        'maximum': 1,
                        'default': 0,
                    }
                    for i in range(count)
                ],
                'sources': [
                    {'name': f's{i}', 'scope': 'voice', 'minimum': 0, 'maximum': 1}
                    for i in range(count)
                ],
            },
            context=CONTEXT,
        )
    elif kind == 'bindings':
        definition = modulation.Modulation.model_validate(
            {
                'sources': [
                    {'name': f's{i}', 'scope': 'voice', 'minimum': 0, 'maximum': 1}
                    for i in range(count)
                ]
            },
            context=CONTEXT,
        )
        bindings = [
            processing.EventBinding(name=f's{i}', kind='velocity') for i in range(count)
        ]
        assert processing.validate_local_bindings(definition, bindings, {}) == []
    elif kind == 'identifier':
        TypeAdapter(modulation_contract.Identifier).validate_python(
            'a' * count, context=CONTEXT
        )
    elif kind == 'identifier_unicode':
        TypeAdapter(modulation_contract.Identifier).validate_python(
            'é' * count, context=CONTEXT
        )
    elif kind == 'quantity':
        assert (
            modulation_contract.scalar_quantity('1' + ' ' * (count - 1), 'ratio') == 1
        )
    else:
        raise AssertionError(f'Unknown preparation operation {kind}')


def test_unicode_provenance_and_python_authoring_remain_explicit() -> None:
    assert (
        json.loads(files('ufor').joinpath('identifier_ranges.json').read_bytes())[
            'unicode_version'
        ]
        == DATA['unicode_version']
    )
    source = modulation.Source(name='x', scope='voice', minimum='0', maximum='1')
    assert source.minimum == 0
    with pytest.raises(ValueError):
        modulation.Source.model_validate(
            {'name': 'x', 'scope': 'voice', 'minimum': '0', 'maximum': '1'},
            context=CONTEXT,
        )
    parameter = modulation.Parameter(
        target=modulation.Target(name='a', parameter='x'),
        unit='volts',
        scope='voice',
        minimum=0,
        maximum='2 kilovolt',
        default='1 kilovolt',
    )
    assert parameter.default == 1000
    assert (
        modulation.Parameter.model_validate(parameter, context=CONTEXT).default == 1000
    )


def test_portable_revalidation_rejects_invalid_edited_points() -> None:
    route = modulation.Route(
        name='r',
        source='x',
        target=modulation.Target(name='a', parameter='x'),
        unit='ratio',
        operation='add',
        points=[modulation.Point(input=0, amount=1)],
    )
    route.points.append(modulation.Point(input=0, amount=2))
    with pytest.raises(ValueError):
        modulation.Route.model_validate(route, context=CONTEXT)


def test_local_validation_rejects_an_invalid_edited_graph() -> None:
    definition = modulation.Modulation().model_copy(
        update={'routes': [{'name': 'incomplete'}]}
    )
    with pytest.raises(ValueError):
        processing.validate_local_bindings(definition, [], {})
