import pytest

from ufor.motion_random import random_word, stream_key
from ufor.samples.processing import MotionEventConnection


@pytest.mark.parametrize(
    ('state', 'expected'),
    [
        (0, 0xE220A8397B1DCDAF),
        (0x9E3779B97F4A7C15, 0x6E789E6AA1B965F4),
        (0x3C6EF372FE94F82A, 0x06C45D188009454F),
    ],
)
def test_motion_random_words_match_portable_vectors(state: int, expected: int) -> None:
    next_state, word = random_word(state)
    assert next_state == (state + 0x9E3779B97F4A7C15) % 2**64
    assert word == expected


def test_motion_streams_depend_on_seed_and_identity() -> None:
    assert stream_key(0, 'voice-0') == stream_key(0, 'voice-0')
    assert stream_key(0, 'voice-0') != stream_key(1, 'voice-0')
    assert stream_key(0, 'voice-0') != stream_key(0, 'voice-1')


@pytest.mark.parametrize('probability', [-0.1, 1.1, float('nan'), float('inf'), True])
def test_event_gate_rejects_invalid_probabilities(probability: float) -> None:
    with pytest.raises(ValueError):
        MotionEventConnection(
            source='clock',
            port='pulse',
            destination='accent',
            cue='hit',
            probability=probability,
        )
