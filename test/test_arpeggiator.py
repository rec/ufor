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
    HitStep,
    Octaves,
    PitchRegister,
    Shuffle,
)
from ufor.codec import parse_score, score_toml


@pytest.mark.parametrize('boundary', ['drop', 'fold', 'error'])
def test_register_profiles_round_trip_with_inclusive_bounds(boundary: str) -> None:
    score = ArpeggiatorScore.model_validate(
        {
            'name': 'register',
            'title': 'Register',
            'body': {
                'rhythm': {'kind': 'grid', 'step': '1/4 beat'},
                'register_limits': {'low': 48, 'high': 72, 'boundary': boundary},
            },
        }
    )
    assert parse_score(score_toml(score)) == score
    assert PitchRegister(low=60, high=60).low == 60


@pytest.mark.parametrize(
    'bounds',
    [
        {'low': 73, 'high': 72},
        {'low': -1},
        {'high': 128},
        {'low': True},
        {'high': 60.5},
        {'boundary': 'clamp'},
    ],
)
def test_register_rejects_invalid_bounds_and_policies(
    bounds: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        PitchRegister.model_validate(bounds)


@pytest.mark.parametrize('traversal', ['notes_first', 'octaves_first'])
def test_octave_profiles_round_trip_with_signed_and_repeated_layers(
    traversal: str,
) -> None:
    score = ArpeggiatorScore.model_validate(
        {
            'kind': 'arpeggiator',
            'name': 'octaves',
            'title': 'Octaves',
            'body': {
                'rhythm': {'kind': 'grid', 'step': '1/4 beat'},
                'octaves': {'offsets': [-1, 0, 1, 0], 'traversal': traversal},
            },
        }
    )
    assert parse_score(score_toml(score)) == score


@pytest.mark.parametrize('offsets', [[], [True], [0.5], [2**63]])
def test_octave_layers_require_nonempty_signed_integer_offsets(
    offsets: list[object],
) -> None:
    with pytest.raises(ValidationError):
        Octaves.model_validate({'offsets': offsets})


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


@pytest.mark.parametrize('kind', ['grid', 'euclidean'])
def test_swung_rhythms_round_trip_exact_pair_shares(kind: str) -> None:
    rhythm = {'kind': kind, 'step': '1/4 beat', 'swing': '2/3'}
    if kind == 'euclidean':
        rhythm.update(steps=5, pulses=3)
    score = ArpeggiatorScore.model_validate(
        {'name': 'swing', 'title': 'Swing', 'body': {'rhythm': rhythm}}
    )
    assert score.body.rhythm.swing == Fraction(2, 3)
    assert parse_score(score_toml(score)) == score
    assert Grid(step='1/4 beat').swing == Fraction(1, 2)


@pytest.mark.parametrize('swing', ['0', '1/3', '1', '3/2'])
def test_swing_requires_a_long_first_step_and_positive_second_step(swing: str) -> None:
    with pytest.raises(ValidationError):
        Grid(step='1/4 beat', swing=Fraction(swing))


def test_custom_patterns_reject_swing() -> None:
    with pytest.raises(ValidationError):
        ArpeggiatorScore.model_validate(
            {
                'name': 'swing',
                'title': 'Swing',
                'body': {
                    'rhythm': {
                        'kind': 'pattern',
                        'swing': '2/3',
                        'steps': [{'kind': 'hit', 'duration': '1/4 beat'}],
                    }
                },
            }
        )


def test_accent_and_gate_patterns_round_trip_independent_exact_multipliers() -> None:
    score = ArpeggiatorScore.model_validate(
        {
            'name': 'patterns',
            'title': 'Patterns',
            'body': {
                'rhythm': {'kind': 'grid', 'step': '1/4 beat'},
                'patterns': {'accents': ['1', '1/2', '0', '2'], 'gates': ['1', '1/2']},
            },
        }
    )
    assert score.body.patterns is not None
    assert score.body.patterns.accents == [
        Fraction(1),
        Fraction(1, 2),
        Fraction(0),
        Fraction(2),
    ]
    assert parse_score(score_toml(score)) == score


@pytest.mark.parametrize('field', ['accents', 'gates'])
@pytest.mark.parametrize('values', [[], [-1], [0.5], [True], ['1/0']])
def test_step_patterns_require_nonempty_nonnegative_exact_values(
    field: str, values: list[object]
) -> None:
    from ufor.arpeggiator import StepPatterns

    with pytest.raises(ValidationError):
        StepPatterns.model_validate({field: values})


@pytest.mark.parametrize(
    'condition',
    [
        {'passes': [], 'out_of': 4},
        {'passes': [0], 'out_of': 4},
        {'passes': [5], 'out_of': 4},
        {'passes': [1, 1], 'out_of': 4},
        {'passes': [1], 'out_of': 0},
        {'passes': [True], 'out_of': 4},
        {'passes': [1], 'out_of': 1.5},
        {'passes': [1], 'out_of': 4, 'unknown': 1},
    ],
)
def test_hit_rejects_invalid_pass_conditions(condition: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        HitStep.model_validate({'duration': '1/4 beat', 'condition': condition})


def test_conditional_hits_round_trip_without_changing_unconditional_hits() -> None:
    score = ArpeggiatorScore.model_validate(
        {
            'name': 'conditional',
            'title': 'Conditional',
            'body': {
                'rhythm': {
                    'kind': 'pattern',
                    'steps': [
                        {
                            'kind': 'hit',
                            'duration': '1/4 beat',
                            'condition': {'passes': [1, 3], 'out_of': 4},
                        },
                        {'kind': 'hit', 'duration': '1/4 beat'},
                    ],
                }
            },
        }
    )
    assert parse_score(score_toml(score)) == score
    assert score_toml(score).count('out_of') == 1
