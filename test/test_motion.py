from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.codec import parse_score, score_toml
from ufor.library_files import read_library
from ufor.motion import (
    Contour,
    Cycle,
    EnterStage,
    FinishStage,
    Hold,
    Marker,
    MotionEvent,
    MotionParameter,
    MotionScore,
    MotionState,
    MotionUse,
    ParameterReference,
    Stage,
    Stages,
    StageTransition,
    advance_motion,
    initial_motion,
    instantiate_motion,
    motion_at,
    motion_event,
)
from ufor.segments import Segment


def staged_motion() -> MotionUse:
    return MotionUse(
        body=Stages(
            initial_stage='waiting',
            stages=[
                Stage(name='waiting', motion=Hold(value=0.0)),
                Stage(
                    name='attack',
                    motion=Contour(
                        initial='current',
                        segments=[Segment(duration=Fraction(1, 4), to=0.7)],
                    ),
                ),
                Stage(
                    name='sway',
                    motion=Cycle(
                        rate=Fraction(2),
                        center=0.7,
                        depth=0.2,
                        markers=[Marker(name='peak', position=Fraction(1, 4))],
                    ),
                ),
                Stage(
                    name='release',
                    motion=Contour(
                        initial='current',
                        segments=[Segment(duration=Fraction(1, 4), to=0.0)],
                    ),
                ),
            ],
            transitions=[
                StageTransition(
                    from_stages=['waiting', 'attack', 'sway', 'release'],
                    event='note_on',
                    action=EnterStage(stage='attack'),
                ),
                StageTransition(
                    from_stages=['attack'],
                    event='stage.done',
                    action=EnterStage(stage='sway'),
                ),
                StageTransition(
                    from_stages=['attack', 'sway'],
                    event='note_off',
                    action=EnterStage(stage='release'),
                ),
                StageTransition(
                    from_stages=['release'],
                    event='stage.done',
                    action=FinishStage(),
                ),
                StageTransition(
                    from_stages=['waiting'],
                    event='cue.sway',
                    action=EnterStage(stage='sway'),
                ),
            ],
        )
    )


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


def test_public_cycle_rate_is_explicitly_bound_and_instantiated() -> None:
    score = MotionScore(
        name='vibrato',
        title='Vibrato',
        parameters={
            'speed': MotionParameter(unit='hz', default=5, minimum=0.1, maximum=20)
        },
        body=Cycle(rate=ParameterReference(parameter='speed')),
    )
    assert parse_score(score_toml(score)) == score
    assert instantiate_motion(score).body == Cycle(rate=Fraction(5))
    assert instantiate_motion(score, {'speed': 6}).body == Cycle(rate=Fraction(6))
    with pytest.raises(ValueError, match='unknown public'):
        instantiate_motion(score, {'depth': 1})
    with pytest.raises(ValueError, match='outside its range'):
        instantiate_motion(score, {'speed': 30})
    with pytest.raises(ValidationError, match='inline cycle rate'):
        MotionUse(body=score.body)


def test_motion_use_requires_exactly_one_definition() -> None:
    with pytest.raises(ValidationError, match='exactly one'):
        MotionUse()
    with pytest.raises(ValidationError, match='exactly one'):
        MotionUse.model_validate(
            {'body': {'kind': 'cycle', 'rate': '1'}, 'score': {'selector': 'vibrato'}}
        )


def test_example_motion_library_resolves_all_scores() -> None:
    library = read_library(Path(__file__).parents[1] / 'examples/motions/library.toml')
    assert not library.diagnostics
    assert {e.name for e in library.find()} == {
        'vibrato',
        'pulse',
        'pluck',
        'bloom',
    }


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


def test_stages_attack_sways_releases_and_emits_completion() -> None:
    motion = staged_motion()
    assert MotionUse.model_validate_json(motion.model_dump_json()) == motion
    score = MotionScore(name='bloom', title='Bloom', body=motion.body)
    assert parse_score(score_toml(score)) == score
    state = initial_motion(motion, Fraction(0))
    assert motion_at(motion, state, Fraction(0)).value == 0
    start = advance_motion(
        motion,
        state,
        Fraction(0),
        MotionEvent(at=Fraction(0), ordinal=0, action='note_on'),
    )
    attack_end = advance_motion(motion, start.state, Fraction(1, 4))
    assert attack_end.value.value == pytest.approx(0.7)
    assert [(e.at, e.port, e.stage) for e in attack_end.events] == [
        (Fraction(1, 4), 'stage.done', 'attack')
    ]
    peak = advance_motion(motion, attack_end.state, Fraction(3, 8))
    assert peak.value.value == pytest.approx(0.9)
    assert [(e.at, e.port, e.stage) for e in peak.events] == [
        (Fraction(3, 8), 'peak', 'sway')
    ]
    release = advance_motion(
        motion,
        peak.state,
        Fraction(3, 8),
        MotionEvent(at=Fraction(3, 8), ordinal=0, action='note_off'),
    )
    assert release.value.value == pytest.approx(0.9)
    restored = MotionState.model_validate_json(release.state.model_dump_json())
    done = advance_motion(motion, restored, Fraction(5, 8))
    assert done.value.status == 'complete'
    assert done.value.value == pytest.approx(0)
    assert [(e.port, e.stage) for e in done.events] == [
        ('stage.done', 'release'),
        ('done', 'release'),
    ]
    assert advance_motion(motion, done.state, Fraction(1)).events == []


def test_note_off_at_stage_end_discards_obsolete_completion() -> None:
    motion = staged_motion()
    start = advance_motion(
        motion,
        initial_motion(motion, Fraction(0)),
        Fraction(0),
        MotionEvent(at=Fraction(0), ordinal=0, action='note_on'),
    )
    release = advance_motion(
        motion,
        start.state,
        Fraction(1, 4),
        MotionEvent(at=Fraction(1, 4), ordinal=0, action='note_off'),
    )
    assert release.events == []
    assert release.value.value == pytest.approx(0.7)
    assert release.state.runtime.stage == 'release'
    done = advance_motion(motion, release.state, Fraction(1, 2))
    assert [e.port for e in done.events] == ['stage.done', 'done']


def test_stage_cue_and_marker_crossings_are_partition_independent() -> None:
    motion = staged_motion()
    cue = MotionEvent(at=Fraction(0), ordinal=0, action='cue', cue='sway')
    start = advance_motion(motion, initial_motion(motion, Fraction(0)), cue.at, cue)
    whole = advance_motion(motion, start.state, Fraction(1))
    pieces = []
    state = start.state
    for end in (Fraction(1, 8), Fraction(1, 4), Fraction(3, 4), Fraction(1)):
        result = advance_motion(motion, state, end)
        pieces.extend(result.events)
        state = result.state
    assert [(e.at, e.port) for e in whole.events] == [
        (Fraction(1, 8), 'peak'),
        (Fraction(5, 8), 'peak'),
    ]
    assert pieces == whole.events
    assert motion_at(motion, state, Fraction(1)) == whole.value
