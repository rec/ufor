"""Portable generator definitions and exact preparation foundations."""

import json
from fractions import Fraction
from pathlib import Path

import pytest
import tomlkit
from pydantic import TypeAdapter

from ufor import envelfo, envelfo_contract, modulation_contract
from ufor.approach import ExponentialApproach
from ufor.samples.processing import SoundSettings
from ufor.segments import IndefiniteSegment

DATA = json.loads(
    (Path(__file__).parents[1] / 'conformance/envelfo-definitions.json').read_bytes()
)
ADAPTER = TypeAdapter(envelfo.Generator)
CONTEXT = {'portable': True}


def same(actual: object, expected: object) -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        for key, value in expected.items():
            same(actual[key], value)
    elif isinstance(expected, list):
        assert isinstance(actual, (list, tuple)) and len(actual) == len(expected)
        for a, e in zip(actual, expected, strict=True):
            same(a, e)
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert isinstance(actual, (int, float)) and not isinstance(actual, bool)
        assert actual == pytest.approx(
            expected, abs=DATA['absolute_tolerance'], rel=DATA['relative_tolerance']
        )
    elif isinstance(expected, bool):
        assert actual is expected
    else:
        assert actual == expected


@pytest.mark.parametrize('case', DATA['definitions'], ids=lambda c: c['id'])
def test_generator_definitions_and_interchange(case: dict[str, object]) -> None:
    if case.get('rejected'):
        with pytest.raises(ValueError):
            ADAPTER.validate_python(case['input'], context=CONTEXT)
        return
    value = ADAPTER.validate_python(case['input'], context=CONTEXT)
    same(value.model_dump(mode='json'), case.get('expected', {}))
    assert ADAPTER.validate_json(value.model_dump_json(), context=CONTEXT) == value
    text = tomlkit.dumps(value.model_dump(mode='json', exclude_none=True))
    assert (
        ADAPTER.validate_python(tomlkit.parse(text).unwrap(), context=CONTEXT) == value
    )
    if 'ranges' in case:
        assert isinstance(value, envelfo.Patch)
        same(value.signal_ranges, case['ranges'])
        positions = {n: i for i, n in enumerate(value.signal_order)}
        for name, child in value.envelfos.items():
            inputs = (
                child.inputs
                if isinstance(child, (envelfo.Sum, envelfo.Product))
                else [child.input]
                if isinstance(
                    child,
                    (
                        envelfo.Affine,
                        envelfo.Quantize,
                        envelfo.Latch,
                        envelfo.Threshold,
                        envelfo.Slew,
                    ),
                )
                else []
            )
            assert all(positions[i] < positions[name] for i in inputs)
    if 'output_order' in case:
        assert isinstance(value, envelfo.Patch)
        assert list(value.outputs) == case['output_order']


@pytest.mark.parametrize('case', DATA['quantities'], ids=lambda c: c['id'])
def test_exact_generator_quantities(case: dict[str, object]) -> None:
    if case.get('rejected'):
        with pytest.raises(ValueError):
            modulation_contract.exact_quantity(case['input'], str(case['unit']))
    else:
        assert modulation_contract.exact_quantity(
            case['input'], str(case['unit'])
        ) == Fraction(str(case['expected']))


@pytest.mark.parametrize('case', DATA['quantity_text_limits'])
def test_quantity_text_length_is_bounded(case: dict[str, object]) -> None:
    text = '1' + ' ' * (int(case['length']) - 1)
    if case['accepted']:
        assert modulation_contract.exact_quantity(text, 'seconds') == 1
    else:
        with pytest.raises(ValueError, match='4096'):
            modulation_contract.exact_quantity(text, 'seconds')


@pytest.mark.parametrize('case', DATA['budgets'], ids=lambda c: c['id'])
def test_preparation_records_count_declarations_and_references(
    case: dict[str, object],
) -> None:
    count = int(case['records'])
    assert envelfo_contract.preparation_records(case['input'], count) == count
    with pytest.raises(ValueError, match='preparation'):
        envelfo_contract.preparation_records(case['input'], count - 1)


def test_preparation_override_can_exceed_default() -> None:
    value = {'kind': 'envelope', 'segments': [{'duration': None}] * 10000}
    with pytest.raises(ValueError, match='10000'):
        envelfo_contract.preparation_records(value)
    assert envelfo_contract.preparation_records(value, 10001) == 10001
    assert envelfo_contract.preparation_records({}, 1) == 1
    with pytest.raises(ValueError):
        envelfo_contract.preparation_records({}, 0)


@pytest.mark.parametrize('limit', [True, -1, 1.0, '10000', 2**63])
def test_invalid_preparation_limit_is_rejected(limit: object) -> None:
    with pytest.raises(ValueError, match='max_records'):
        envelfo_contract.record_limit(limit)


@pytest.mark.parametrize('case', DATA['quantizers'], ids=lambda c: c['id'])
def test_quantizer_ties_choose_the_higher_grid_point(case: dict[str, object]) -> None:
    definition = envelfo.Quantize(
        input='source', step=float(case['step']), origin=float(case['origin'])
    )
    same(envelfo.quantize_value(definition, float(case['value'])), case['expected'])


@pytest.mark.parametrize('case', DATA['approaches'], ids=lambda c: c['id'])
def test_captured_approach_normalizes_segments_once(case: dict[str, object]) -> None:
    definition = ExponentialApproach.model_validate(case['input'])
    same(
        [s.model_dump(mode='json') for s in definition.resolve(float(case['initial']))],
        case['expected'],
    )


def test_top_level_bound_envelope_still_requires_an_explicit_initial_level() -> None:
    with pytest.raises(ValueError, match='current envelope initial requires a parent'):
        SoundSettings(
            envelfos={
                'hold': envelfo.Envelope(
                    initial='current', segments=[IndefiniteSegment()]
                )
            }
        )
