"""Portable generator definitions and exact preparation foundations."""

import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest
import tomlkit
from pydantic import TypeAdapter

from ufor import envelfo, envelfo_contract, modulation_contract
from ufor.approach import ExponentialApproach
from ufor.samples.processing import SoundSettings
from ufor.segments import IndefiniteSegment, Segment

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


@pytest.mark.parametrize('case', DATA['segments'], ids=lambda c: c['id'])
def test_shared_segment_boundary_keeps_nongenerator_levels(
    case: dict[str, object],
) -> None:
    if case.get('rejected'):
        with pytest.raises(ValueError):
            Segment.model_validate(case['input'], context=CONTEXT)
    else:
        value = Segment.model_validate(case['input'], context=CONTEXT)
        same(value.model_dump(mode='json'), case['expected'])
        assert Segment.model_validate(value, context=CONTEXT) == value


@pytest.mark.parametrize('case', DATA['ordered_documents'], ids=lambda c: c['id'])
def test_output_order_survives_document_roundtrips(case: dict[str, object]) -> None:
    data = (
        json.loads(str(case['text']))
        if case['format'] == 'json'
        else tomlkit.parse(str(case['text'])).unwrap()
    )
    value = ADAPTER.validate_python(data, context=CONTEXT)
    assert isinstance(value, envelfo.Patch)
    assert list(value.outputs) == case['outputs']
    for decoded in (
        json.loads(value.model_dump_json()),
        tomlkit.parse(
            tomlkit.dumps(value.model_dump(mode='json', exclude_none=True))
        ).unwrap(),
    ):
        restored = ADAPTER.validate_python(decoded, context=CONTEXT)
        assert isinstance(restored, envelfo.Patch)
        assert list(restored.outputs) == case['outputs']


@pytest.mark.parametrize('case', DATA['approach_errors'], ids=lambda c: c['id'])
def test_approach_resolution_rejects_overflow(case: dict[str, object]) -> None:
    value = ExponentialApproach.model_validate(case['input'], context=CONTEXT)
    with pytest.raises(ValueError):
        value.resolve(float(case['initial']))


@pytest.mark.parametrize('case', DATA['text_limits'], ids=lambda c: c['id'])
def test_generator_text_limits_precede_canonicalization(
    case: dict[str, object],
) -> None:
    value = deepcopy(case['input'])
    target = value
    for key in case['path'][:-1]:
        target = target[key]
    target[case['path'][-1]] = ' ' * int(case['length'])
    if case['accepted']:
        ADAPTER.validate_python(value, context=CONTEXT)
    else:
        with pytest.raises(ValueError, match='4096'):
            ADAPTER.validate_python(value, context=CONTEXT)


def test_portable_budget_counts_models_and_uses_one_override() -> None:
    value = envelfo.Envelope(segments=[Segment(duration=0, to=1)] * 10000)
    with pytest.raises(ValueError, match='10000'):
        ADAPTER.validate_python(value, context=CONTEXT)
    result = ADAPTER.validate_python(value, context=CONTEXT | {'max_records': 10001})
    assert isinstance(result, envelfo.Envelope) and len(result.segments) == 10000
    patch = envelfo.Patch(envelfos={'a': value}, outputs={'out': 'a'})
    with pytest.raises(ValueError):
        ADAPTER.validate_python(patch, context=CONTEXT | {'max_records': 10002})
    ADAPTER.validate_python(patch, context=CONTEXT | {'max_records': 10003})


def test_portable_revalidation_rejects_edited_nested_values_and_settings() -> None:
    segment = Segment(duration=0, to=1).model_copy(update={'duration': 0.25})
    value = envelfo.Envelope(segments=[Segment(duration=0, to=1)])
    value.segments[0] = segment
    with pytest.raises(ValueError):
        ADAPTER.validate_python(value, context=CONTEXT)
    patch = envelfo.Patch(envelfos={'a': envelfo.LFO(rate=1)}, outputs={'out': 'a'})
    patch.envelfos['a'] = patch.envelfos['a'].model_copy(update={'scope': 'part'})
    with pytest.raises(ValueError, match='parent'):
        ADAPTER.validate_python(patch, context=CONTEXT)


def test_authoring_coercions_and_broader_units_normalize_before_portability() -> None:
    value = envelfo.LFO(rate='1 * Hz', center=0)
    assert (
        ADAPTER.validate_python(value, context=CONTEXT).model_dump()
        == value.model_dump()
    )
    value = envelfo.Envelope(
        hold=1,
        playback='loop',
        repeat_count='2',
        segments=[Segment(duration='1 second', to=1, curve='0')],
    )
    assert ADAPTER.validate_python(value, context=CONTEXT) == value


def test_slew_scalar_rate_is_not_limited_to_exact_time_range() -> None:
    value = envelfo.Slew.model_validate(
        {'input': 'source', 'rise': '1e-200/s', 'fall': 2}, context=CONTEXT
    )
    assert value.rise == 1e-200


def test_portable_graph_validation_does_not_trust_cached_ranges() -> None:
    value = envelfo.Patch(
        envelfos={'a': envelfo.LFO(rate=1), 'mix': envelfo.Sum(inputs=['a', 'a'])},
        outputs={'out': 'mix'},
    )
    assert value.signal_ranges['mix'] == (-2, 2)
    node = value.envelfos['mix']
    assert isinstance(node, envelfo.Sum)
    node.inputs[0] = 'missing'
    with pytest.raises(ValueError, match='unknown child'):
        ADAPTER.validate_python(value, context=CONTEXT)
