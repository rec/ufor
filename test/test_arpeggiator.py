from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.arpeggiator import (
    ArpeggiatorScore,
    Ascending,
    Choice,
    Descending,
    Grid,
    HeldBank,
    Shuffle,
)
from ufor.codec import parse_score, score_toml


@pytest.mark.parametrize(
    'name',
    [
        'up',
        'wind-memory',
        'five-in-eight',
        'sample-notes',
        'custom-steps',
        'weighted-walk',
        'alternating',
        'inside-out',
        'outside-in',
        'index-pattern',
        'shuffle',
        'choice',
        'phrase-wind',
    ],
)
def test_authored_arpeggiator_profiles_round_trip(name: str) -> None:
    text = Path(f'conformance/arpeggiator/{name}.toml').read_text()
    score = parse_score(text)
    assert isinstance(score, ArpeggiatorScore)
    assert score.name == name
    assert parse_score(score_toml(score)) == score


def test_simple_profile_has_the_declared_defaults() -> None:
    score = parse_score(Path('conformance/arpeggiator/up.toml').read_text())
    assert isinstance(score, ArpeggiatorScore)
    assert score.body.bank == HeldBank()
    assert score.body.selection == Ascending()
    assert score.body.rhythm == Grid(step='1/4 beat')
    assert score.body.gate == Fraction(4, 5)
    assert score.body.retrigger == 'on_empty'


def test_shuffle_requires_a_seed_and_round_trips_all_policies() -> None:
    score = parse_score(Path('conformance/arpeggiator/shuffle.toml').read_text())
    assert isinstance(score, ArpeggiatorScore)
    assert isinstance(score.body.selection, Shuffle)
    assert score.body.selection.mode == 'cycle'
    assert score.body.selection.on_edit == 'restart'
    assert score.body.selection.no_repeat is False
    data = score.model_dump()
    data['body']['seed'] = None
    with pytest.raises(ValidationError):
        ArpeggiatorScore.model_validate(data)
    data['body']['seed'] = 42
    data['body']['selection'] = {
        'kind': 'shuffle',
        'mode': 'once',
        'no_repeat': True,
        'on_edit': 'preserve',
    }
    score = ArpeggiatorScore.model_validate(data)
    assert parse_score(score_toml(score)) == score


def test_choice_requires_seed_and_round_trips_policies() -> None:
    score = parse_score(Path('conformance/arpeggiator/choice.toml').read_text())
    assert isinstance(score, ArpeggiatorScore)
    assert isinstance(score.body.selection, Choice)
    assert Choice().weights == [1]
    assert score.body.selection.extend == 'ones'
    assert score.body.selection.no_repeat is False
    data = score.model_dump()
    data['body']['seed'] = None
    with pytest.raises(ValidationError):
        ArpeggiatorScore.model_validate(data)
    data['body']['seed'] = 42
    data['body']['selection'] = {
        'kind': 'choice',
        'weights': [4, 1],
        'extend': 'repeat',
        'no_repeat': True,
    }
    score = ArpeggiatorScore.model_validate(data)
    assert parse_score(score_toml(score)) == score


@pytest.mark.parametrize('weights', [[], [0], [-1], [1.5], [True], ['1'], [2**32]])
def test_choice_requires_positive_u32_weights(weights: list[object]) -> None:
    with pytest.raises(ValidationError):
        Choice.model_validate({'weights': weights})


@pytest.mark.parametrize('option,value', [('extend', 'last'), ('no_repeat', 1)])
def test_choice_rejects_invalid_policies(option: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Choice.model_validate({option: value})


@pytest.mark.parametrize(
    'option,value', [('mode', 'random'), ('on_edit', 'append'), ('no_repeat', 1)]
)
def test_shuffle_rejects_invalid_policies(option: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Shuffle.model_validate({option: value})


@pytest.mark.parametrize('indices', [[], [-1], [1.5], [True], ['1']])
def test_index_pattern_requires_nonnegative_integer_indices(
    indices: list[object],
) -> None:
    from ufor.arpeggiator import IndexPattern

    with pytest.raises(ValidationError):
        IndexPattern.model_validate({'indices': indices})


def test_index_pattern_boundary_defaults_to_wrap_and_accepts_rest() -> None:
    from ufor.arpeggiator import IndexPattern

    assert IndexPattern(indices=[0, 5]).boundary == 'wrap'
    assert IndexPattern(indices=[0], boundary='rest').boundary == 'rest'
    with pytest.raises(ValidationError):
        IndexPattern.model_validate({'indices': [0], 'boundary': 'clamp'})


def test_bank_edit_retrigger_round_trips() -> None:
    data = {
        'name': 'restart-on-edit',
        'title': 'Restart on chord edit',
        'body': {
            'rhythm': {'kind': 'grid', 'step': '1/4 beat'},
            'retrigger': 'bank_edit',
        },
    }
    score = ArpeggiatorScore.model_validate(data)
    assert score.body.retrigger == 'bank_edit'
    assert parse_score(score_toml(score)) == score


def test_descending_profile_is_supported() -> None:
    score = ArpeggiatorScore.model_validate(
        {
            'name': 'down',
            'title': 'Down',
            'body': {
                'selection': {'kind': 'descending'},
                'rhythm': {'kind': 'grid', 'step': '1/4 beat'},
            },
        }
    )
    assert score.body.selection == Descending()
    assert parse_score(score_toml(score)) == score


@pytest.mark.parametrize('step', ['0 beat', '-1 beat', '1/0 beat', '1/4', 'abc beat'])
def test_grid_rejects_invalid_beat_durations(step: str) -> None:
    with pytest.raises(ValidationError, match='positive rational beat duration'):
        Grid(step=step)


@pytest.mark.parametrize(
    'steps',
    [
        [],
        [{'kind': 'hit', 'duration': '0 beat'}],
        [{'kind': 'hit', 'duration': '1/4 beat', 'repeats': 0}],
        [{'kind': 'hit', 'duration': '1/4 beat', 'repeats': 1.5}],
        [{'kind': 'tie', 'duration': '1/4 beat', 'repeats': 2}],
    ],
)
def test_pattern_rejects_invalid_steps(steps: list[dict[str, object]]) -> None:
    with pytest.raises(ValidationError):
        ArpeggiatorScore.model_validate(
            {
                'name': 'pattern',
                'title': 'Pattern',
                'body': {'rhythm': {'kind': 'pattern', 'steps': steps}},
            }
        )


@pytest.mark.parametrize('probability', ['-1/2', '3/2', '1/2'])
def test_probability_rejects_out_of_range_or_unseeded_choices(probability: str) -> None:
    with pytest.raises(ValidationError):
        ArpeggiatorScore.model_validate(
            {
                'name': 'chance',
                'title': 'Chance',
                'body': {
                    'rhythm': {'kind': 'grid', 'step': '1/4 beat'},
                    'probability': probability,
                },
            }
        )


def test_seeded_probability_round_trips() -> None:
    score = ArpeggiatorScore.model_validate(
        {
            'name': 'chance',
            'title': 'Chance',
            'body': {
                'rhythm': {'kind': 'grid', 'step': '1/4 beat'},
                'probability': '1/3',
                'seed': 42,
            },
        }
    )
    assert score.body.probability == Fraction(1, 3)
    assert parse_score(score_toml(score)) == score


@pytest.mark.parametrize('repeat_endpoints', [False, True])
def test_alternating_endpoint_policy_round_trips(repeat_endpoints: bool) -> None:
    score = ArpeggiatorScore.model_validate(
        {
            'name': 'alternating',
            'title': 'Alternating',
            'body': {
                'rhythm': {'kind': 'grid', 'step': '1/4 beat'},
                'selection': {
                    'kind': 'alternating',
                    'repeat_endpoints': repeat_endpoints,
                },
            },
        }
    )
    assert parse_score(score_toml(score)) == score
