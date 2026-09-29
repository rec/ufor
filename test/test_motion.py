from fractions import Fraction

import pytest
from pydantic import ValidationError

from ufor.codec import parse_score, score_toml
from ufor.motion import (
    Contour,
    Cycle,
    MotionEvent,
    MotionScore,
    MotionState,
    MotionUse,
    initial_motion,
    motion_at,
    motion_event,
)
from ufor.segments import Segment


@pytest.mark.parametrize(
    ('body', 'expected'),
    [
        ('kind = "cycle"\nshape = "sine"\nrate = "5 Hz"', Cycle),
        (
            'kind = "contour"\ninitial = 0.0\n'
            'segments = [{ duration = "10 ms", to = 1.0 }]\n'
            'release = [{ duration = "200 ms", to = 0.0 }]',
            Contour,
        ),
    ],
)
def test_motion_score_round_trips_simple_bodies(
    body: str, expected: type[object]
) -> None:
    document = parse_score(
        f'kind = "motion"\nname = "example"\ntitle = "Example"\n[body]\n{body}\n'
    )
    assert isinstance(document, MotionScore)
    assert isinstance(document.body, expected)
    assert parse_score(score_toml(document)) == document


@pytest.mark.parametrize('kind', ['lfo', 'envelope'])
def test_old_generator_score_kinds_are_rejected(kind: str) -> None:
    with pytest.raises(ValidationError):
        parse_score(f'kind = "{kind}"\nname = "old"\ntitle = "Old"\n')


def test_autonomous_contour_completes_without_note_off() -> None:
    motion = MotionUse(body=Contour(segments=[Segment(duration=Fraction(1), to=1)]))
    state = initial_motion(motion, Fraction(2))
    assert motion_at(motion, state, Fraction(2)).status == 'running'
    assert motion_at(motion, state, Fraction(5, 2)).value == 0.5
    state = motion_event(
        motion,
        state,
        MotionEvent(at=Fraction(5, 2), ordinal=0, action='note_off'),
    )
    assert motion_at(motion, state, Fraction(3)).status == 'complete'
    assert motion_at(motion, state, Fraction(3)).value == 1
    restored = MotionState.model_validate_json(state.model_dump_json())
    assert motion_at(motion, restored, Fraction(3)) == motion_at(
        motion, state, Fraction(3)
    )


def test_triggered_contour_holds_then_releases_from_current_value() -> None:
    motion = MotionUse(
        body=Contour(
            segments=[Segment(duration=Fraction(1), to=1)],
            release=[Segment(duration=Fraction(1), to=0)],
        )
    )
    state = initial_motion(motion, Fraction(0))
    assert motion_at(motion, state, Fraction(0)).status == 'idle'
    state = motion_event(
        motion, state, MotionEvent(at=Fraction(0), ordinal=0, action='note_on')
    )
    assert motion_at(motion, state, Fraction(1)).status == 'held'
    state = motion_event(
        motion, state, MotionEvent(at=Fraction(3, 2), ordinal=0, action='note_off')
    )
    assert motion_at(motion, state, Fraction(2)).value == 0.5
    assert motion_at(motion, state, Fraction(5, 2)).status == 'complete'


def test_cycle_uses_same_value_and_event_contract() -> None:
    motion = MotionUse(body=Cycle(rate=Fraction(1)))
    state = initial_motion(motion, Fraction(0))
    state = motion_event(
        motion,
        state,
        MotionEvent(at=Fraction(1, 4), ordinal=0, action='rate', rate=Fraction(2)),
    )
    assert motion_at(motion, state, Fraction(1, 2)).value == pytest.approx(-1)
    assert motion_at(motion, state, Fraction(1, 2)).status == 'running'
    state = motion_event(
        motion, state, MotionEvent(at=Fraction(1, 2), ordinal=0, action='note_off')
    )
    assert motion_at(motion, state, Fraction(3, 4)).value == pytest.approx(1)
    restored = MotionState.model_validate_json(state.model_dump_json())
    assert motion_at(motion, restored, Fraction(3, 4)) == motion_at(
        motion, state, Fraction(3, 4)
    )
