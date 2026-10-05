from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.arpeggiator import ArpeggiatorScore, Ascending, Descending, Grid, HeldBank
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
