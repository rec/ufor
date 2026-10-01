from fractions import Fraction

import pytest
from pydantic import ValidationError

from ufor.control import TempoMap
from ufor.motion import (
    Contour,
    MotionEvent,
    MotionUse,
    initial_motion,
    motion_at,
    motion_event,
)
from ufor.segments import Segment


def test_host_tempo_map_preserves_exact_beats_through_tempo_stop_and_seek() -> None:
    clock = TempoMap.model_validate(
        {
            'points': [
                {'at_seconds': '0', 'beat': '0', 'bpm': '120'},
                {'at_seconds': '1', 'beat': '2', 'bpm': '60'},
                {'at_seconds': '2', 'beat': '3', 'bpm': '60', 'running': False},
                {'at_seconds': '3', 'beat': '8', 'bpm': '90'},
            ]
        }
    )
    assert [clock.beat_at(Fraction(n, 2)) for n in range(9)] == [
        Fraction(0),
        Fraction(1),
        Fraction(2),
        Fraction(5, 2),
        Fraction(3),
        Fraction(3),
        Fraction(8),
        Fraction(35, 4),
        Fraction(19, 2),
    ]
    restored = TempoMap.model_validate_json(clock.model_dump_json())
    assert restored.beat_at(Fraction(7, 2)) == Fraction(35, 4)
    assert [clock.elapsed_beats(Fraction(0), Fraction(n)) for n in range(5)] == [
        Fraction(0),
        Fraction(2),
        Fraction(3),
        Fraction(3),
        Fraction(9, 2),
    ]
    assert clock.elapsed_beats(Fraction(1, 2), Fraction(7, 2)) == Fraction(11, 4)


def test_host_tempo_map_rejects_ambiguous_ordering_and_nonpositive_rate() -> None:
    for points in (
        [{'at_seconds': '1', 'beat': '0', 'bpm': '120'}],
        [
            {'at_seconds': '0', 'beat': '0', 'bpm': '120'},
            {'at_seconds': '0', 'beat': '2', 'bpm': '60'},
        ],
        [{'at_seconds': '0', 'beat': '0', 'bpm': '0'}],
    ):
        with pytest.raises(ValidationError):
            TempoMap.model_validate({'points': points})
    with pytest.raises(ValueError, match='nonnegative'):
        TempoMap.model_validate(
            {'points': [{'at_seconds': '0', 'beat': '0', 'bpm': '120'}]}
        ).beat_at(Fraction(-1))


def test_beat_contour_follows_host_tempo_and_preserves_authored_unit() -> None:
    clock = TempoMap.model_validate(
        {
            'points': [
                {'at_seconds': '0', 'beat': '0', 'bpm': '120'},
                {'at_seconds': '1', 'beat': '2', 'bpm': '60'},
            ]
        }
    )
    motion = MotionUse.model_validate(
        {
            'clock': 'beats',
            'body': {
                'kind': 'contour',
                'segments': [{'duration': '4 beat', 'to': 1}],
            },
        }
    )
    assert motion.model_dump(mode='json')['body']['segments'][0]['duration'] == '4 beat'
    state = motion_event(
        motion,
        initial_motion(motion, Fraction(0)),
        MotionEvent(at=Fraction(0), ordinal=0, action='note_on'),
    )
    assert motion_at(motion, state, clock.beat_at(Fraction(1))).value == 0.5
    assert motion_at(motion, state, clock.beat_at(Fraction(2))).value == 0.75
    assert isinstance(motion.body, Contour)
    with pytest.raises(ValidationError, match='must match its clock'):
        MotionUse.model_validate(
            {
                'clock': 'beats',
                'body': {
                    'kind': 'contour',
                    'segments': [{'duration': '4 s', 'to': 1}],
                },
            }
        )
    with pytest.raises(ValidationError, match='conflicts with its suffix'):
        Segment.model_validate({'duration': '4 s', 'duration_unit': 'beats', 'to': 1})


def test_quantized_beat_keeps_its_target_through_tempo_change_and_stop() -> None:
    clock = TempoMap.model_validate(
        {
            'points': [
                {'at_seconds': '0', 'beat': '0', 'bpm': '120'},
                {'at_seconds': '1', 'beat': '2', 'bpm': '60'},
                {'at_seconds': '2', 'beat': '3', 'bpm': '60', 'running': False},
                {'at_seconds': '3', 'beat': '3', 'bpm': '90'},
            ]
        }
    )
    target = clock.quantized_beat(Fraction(3, 4), Fraction(1))
    assert target == 2
    assert clock.time_for_beat(target, Fraction(3, 4)) == 1
    assert clock.quantized_beat(Fraction(1), Fraction(1)) == 2
    assert clock.time_for_beat(Fraction(4), Fraction(7, 4)) == Fraction(11, 3)
    assert clock.time_for_beat(Fraction(3), Fraction(5, 2)) == 3
    assert clock.time_for_beat(Fraction(4), Fraction(5, 2)) == Fraction(11, 3)
    with pytest.raises(ValueError, match='positive'):
        clock.quantized_beat(Fraction(0), Fraction(0))


def test_pending_quantized_beat_is_cancelled_on_transport_seek() -> None:
    clock = TempoMap.model_validate(
        {
            'points': [
                {'at_seconds': '0', 'beat': '0', 'bpm': '120'},
                {'at_seconds': '1', 'beat': '2', 'bpm': '120', 'running': False},
                {'at_seconds': '2', 'beat': '8', 'bpm': '120'},
            ]
        }
    )
    target = clock.quantized_beat(Fraction(3, 4), Fraction(4))
    assert target == 4
    with pytest.raises(ValueError, match='transport seek'):
        clock.time_for_beat(target, Fraction(3, 4))
    stopped = TempoMap.model_validate(
        {'points': [{'at_seconds': '0', 'beat': '0', 'bpm': '120', 'running': False}]}
    )
    assert stopped.time_for_beat(Fraction(1), Fraction(0)) is None
