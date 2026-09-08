import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest
import tomlkit
from pydantic import Field, ValidationError

from ufor import envelope, lfo, modulation
from ufor.base import Model


class Case(Model):
    name: str
    definition: str
    values: dict[str, modulation.SourceValue]
    base_values: list[modulation.ParameterValue] = Field(default_factory=list)
    expected: list[modulation.ParameterValue]


def test_routes_consume_actual_envelope_and_lfo_observations() -> None:
    contour = envelope.Envelope.model_validate(
        {
            'segments': [{'duration': '2', 'target': 1}],
            'release': [{'duration': '1', 'target': 0}],
        }
    )
    state = envelope.initial_envelope(contour, Fraction(0))
    state = envelope.envelope_event(
        contour,
        state,
        envelope.EnvelopeEvent(at=Fraction(0), ordinal=0, action='trigger'),
    )
    oscillator = lfo.LFO.model_validate(
        {
            'scope': 'instrument',
            'reset': 'free',
            'rate': '0',
            'waveform': 'triangle',
            'delay': '1',
            'fade_in': '2',
        }
    )
    phase = lfo.initial_lfo(oscillator, Fraction(0))
    for at, expected in [('1/2', 0.25), ('1', 0.5), ('2', 0.6), ('3', 0.2)]:
        position = Fraction(at)
        level = envelope.envelope_at(contour, state, position)
        tremolo = lfo.lfo_at(oscillator, phase, position)
        result = modulation.evaluate(
            DEFINITIONS['amplitude'],
            {
                'envelope': modulation.SourceValue(value=level.value),
                'tremolo': modulation.SourceValue(
                    value=tremolo.value, weight=tremolo.weight
                ),
            },
        )
        assert result[0].value == pytest.approx(expected, abs=TOLERANCE, rel=0)


@pytest.mark.parametrize('field', ['sources', 'parameters', 'routes'])
def test_duplicate_declarations_are_rejected(field: str) -> None:
    raw = deepcopy(DATA['definitions']['amplitude'])
    raw[field].append(raw[field][0])
    with pytest.raises(ValidationError, match='duplicate'):
        modulation.Modulation.model_validate(raw)


@pytest.mark.parametrize(
    'changes',
    [
        {'source': 'missing'},
        {'target': {'node': 'voice', 'parameter': 'missing'}},
        {'unit': 'cents'},
        {'points': [{'input': 0, 'amount': 0}, {'input': 0, 'amount': 1}]},
        {'points': [{'input': 0, 'amount': 0}, {'input': 2, 'amount': 1}]},
    ],
)
def test_invalid_route_references_units_and_domains(changes: dict[str, object]) -> None:
    raw = deepcopy(DATA['definitions']['amplitude'])
    raw['routes'][0].update(changes)
    with pytest.raises(ValidationError):
        modulation.Modulation.model_validate(raw)


def test_addition_requires_the_actual_parameter_unit() -> None:
    raw = deepcopy(DATA['definitions']['frequency-and-pan'])
    raw['routes'][1]['unit'] = 'cents'
    with pytest.raises(ValidationError, match='requires unit hz'):
        modulation.Modulation.model_validate(raw)


@pytest.mark.parametrize('scope', ['voice', 'trigger', 'part'])
def test_child_scope_cannot_implicitly_drive_an_instrument(scope: str) -> None:
    raw = deepcopy(DATA['definitions']['step'])
    raw['sources'][0]['scope'] = scope
    with pytest.raises(ValidationError, match='instrument-scoped'):
        modulation.Modulation.model_validate(raw)


@pytest.mark.parametrize(
    'values',
    [
        {},
        {'missing': {'value': 0}},
        {'switch': {'value': -1}},
    ],
)
def test_observations_must_name_available_sources_in_their_domains(
    values: dict[str, dict[str, float]],
) -> None:
    with pytest.raises(ValueError):
        modulation.evaluate(
            DEFINITIONS['step'],
            {k: modulation.SourceValue.model_validate(v) for k, v in values.items()},
        )


def test_invalid_base_and_final_values_are_rejected_without_clipping() -> None:
    definition = DEFINITIONS['step']
    target = definition.parameters[0].target
    for value in [-1, 0.5]:
        with pytest.raises(ValueError, match='outside its domain'):
            modulation.evaluate(
                definition,
                {'switch': modulation.SourceValue(value=1)},
                [modulation.ParameterValue(target=target, value=value)],
            )
    base = modulation.ParameterValue(target=target, value=0)
    with pytest.raises(ValueError, match='multiple base'):
        modulation.evaluate(
            definition, {'switch': modulation.SourceValue(value=0)}, [base, base]
        )


DATA = json.loads((Path(__file__).parents[1] / 'conformance/routes.json').read_text())
TOLERANCE = DATA['absolute_tolerance']
DEFINITIONS = {
    k: modulation.Modulation.model_validate(v) for k, v in DATA['definitions'].items()
}
CASES = [Case.model_validate(c) for c in DATA['cases']]


@pytest.mark.parametrize('case', CASES, ids=[c.name for c in CASES])
def test_portable_route_cases_and_declaration_order(case: Case) -> None:
    definition = DEFINITIONS[case.definition]
    for routes in [definition.routes, list(reversed(definition.routes))]:
        document = definition.model_dump(mode='json') | {
            'routes': [r.model_dump(mode='json') for r in routes]
        }
        restored = modulation.Modulation.model_validate(
            tomlkit.parse(tomlkit.dumps(document))
        )
        result = modulation.evaluate(restored, case.values, case.base_values)
        assert [v.target for v in result] == [v.target for v in case.expected]
        assert [v.value for v in result] == pytest.approx(
            [v.value for v in case.expected], abs=TOLERANCE, rel=0
        )
