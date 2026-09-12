import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.automation import AutomationScore, evaluate
from ufor.codec import parse_score, score_schema, score_toml

ROOT = Path(__file__).resolve().parents[1]


def example(name: str) -> AutomationScore:
    score = parse_score((ROOT / 'examples' / 'automation' / f'{name}.toml').read_text())
    assert isinstance(score, AutomationScore)
    return score


@pytest.mark.parametrize(
    'case', json.loads((ROOT / 'conformance' / 'automation.json').read_text())['cases']
)
def test_portable_cases(case: dict[str, object]) -> None:
    score = example(str(case['example']))
    actual = evaluate(score, case['tick'], case.get('override'))
    if isinstance(case['expected'], bool):
        assert actual is case['expected']
    else:
        assert actual == pytest.approx(case['expected'])


@pytest.mark.parametrize('name', ['gain', 'frequency', 'gate'])
def test_edit_and_round_trip(name: str) -> None:
    data = example(name).model_dump()
    data['title'] = 'Edited'
    data['body']['curves'][0]['knots'][0]['tick'] = 500
    edited = AutomationScore.model_validate(data)
    assert parse_score(score_toml(edited)) == edited


def test_schema_includes_automation() -> None:
    assert 'automation' in score_schema()['discriminator']['mapping']


@pytest.mark.parametrize(
    ('name', 'field', 'value'),
    [
        ('gain', 'unit', 'hz'),
        ('frequency', 'unit', 'ratio'),
        ('gate', 'unit', 'volts'),
        ('gate', 'default', 1),
        ('gain', 'default', True),
        ('gain', 'default', -1),
        ('frequency', 'default', 0),
        ('frequency', 'default', float('inf')),
    ],
)
def test_reject_incompatible_defaults_and_units(
    name: str, field: str, value: object
) -> None:
    data = example(name).model_dump()
    data['body'][field] = value
    with pytest.raises(ValidationError):
        AutomationScore.model_validate(data)


@pytest.mark.parametrize(
    ('name', 'field', 'value'),
    [
        ('gate', 'interpolation', 'linear'),
        ('gate', 'operation', 'multiply'),
        ('frequency', 'unit', 'ratio'),
        ('gain', 'knots', [{'tick': 0, 'value': 1}, {'tick': 0, 'value': 2}]),
        ('gain', 'knots', [{'tick': True, 'value': 1}]),
        ('gain', 'knots', [{'tick': 0, 'value': False}]),
        ('gate', 'knots', [{'tick': 0, 'value': 1}]),
    ],
)
def test_reject_invalid_curves(name: str, field: str, value: object) -> None:
    data = example(name).model_dump()
    data['body']['curves'][0][field] = value
    with pytest.raises(ValidationError):
        AutomationScore.model_validate(data)


def test_competing_direct_writers_are_rejected() -> None:
    data = example('gain').model_dump()
    data['body']['curves'].append(data['body']['curves'][0] | {'name': 'other'})
    with pytest.raises(ValidationError, match='competing direct writers'):
        AutomationScore.model_validate(data)


def test_explicit_combination_uses_base_then_add_then_multiply() -> None:
    data = example('frequency').model_dump()
    data['body']['curves'] += [
        {
            'name': 'transpose',
            'unit': 'ratio',
            'operation': 'multiply',
            'knots': [{'tick': 2000, 'value': 2}],
        },
        {
            'name': 'offset',
            'unit': 'hz',
            'operation': 'add',
            'knots': [{'tick': 2000, 'value': -10}],
        },
    ]
    score = AutomationScore.model_validate(data)
    assert evaluate(score, 0) == 220
    assert evaluate(score, 1000) == 440
    assert evaluate(score, 2000) == 1300
    data['body']['curves'].reverse()
    assert evaluate(AutomationScore.model_validate(data), 2000) == 1300


def test_combined_values_cannot_leave_quantity_domain() -> None:
    data = example('frequency').model_dump()
    data['body']['curves'] = [
        {
            'name': 'offset',
            'unit': 'hz',
            'operation': 'add',
            'knots': [{'tick': 0, 'value': -220}],
        }
    ]
    with pytest.raises(ValueError, match='positive'):
        evaluate(AutomationScore.model_validate(data), 0)


def test_override_is_validated_even_when_a_curve_replaces_it() -> None:
    with pytest.raises(ValueError, match='nonnegative'):
        evaluate(example('gain'), 2000, -1)


def test_large_native_ticks_keep_exact_interpolation_positions() -> None:
    data = example('gain').model_dump()
    data['body']['curves'][0]['knots'] = [
        {'tick': 10**18, 'value': 0},
        {'tick': 10**18 + 2, 'value': 1},
    ]
    assert evaluate(AutomationScore.model_validate(data), 10**18 + 1) == 0.5
