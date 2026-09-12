"""Transport boundaries, ownership, and inert raw capture."""

import pytest

from ufor.events import ControlChange, MidiEvent, Release, Trigger
from ufor.playback import SequenceSelection, plan_playback, state_at
from ufor.sequence import Sequence
from ufor.time import TickRange


def sequence() -> Sequence:
    return Sequence(
        timebase='clock',
        end=12,
        events=[
            ControlChange(
                tick=0, ordinal=0, scope='part', part='piano', control='gain', value=0.5
            ),
            Trigger(
                tick=1, ordinal=1, part='piano', trigger_id='a', key=60, velocity=0
            ),
            ControlChange(
                tick=2,
                ordinal=2,
                scope='trigger',
                part='piano',
                trigger_id='a',
                control='bend',
                value=0.2,
            ),
            Trigger(tick=4, ordinal=3, part='piano', trigger_id='b', key=60),
            MidiEvent(tick=5, ordinal=4, data=[0x90, 60, 127]),
            Release(tick=6, ordinal=5, part='piano', trigger_id='a'),
            Release(tick=9, ordinal=6, part='piano', trigger_id='b'),
        ],
    )


def test_seek_reconstructs_state_strictly_before_boundary() -> None:
    assert len(state_at(sequence(), 4).triggers) == 1
    assert len(state_at(sequence(), 5).triggers) == 2
    assert len(state_at(sequence(), 7).controls) == 1
    assert state_at(sequence(), 12).triggers == []


def test_loop_closes_each_owned_note_and_preserves_raw_capture() -> None:
    source = sequence()
    loops = plan_playback(
        source,
        SequenceSelection(
            name='phrase', interval=TickRange(start=4, end=9), repetitions=2
        ),
    )
    first, second = loops
    assert [e.kind for e in first.events] == [
        'trigger',
        'control_change',
        'trigger',
        'release',
    ]
    assert first.events[0].velocity == 0
    assert first.controls[0].value == 0.5
    assert first.cleanup[0].tick == second.start == 5
    assert first.cleanup[0].trigger_id != second.cleanup[0].trigger_id
    assert first.events[-1].trigger_id == first.events[0].trigger_id
    assert first.cleanup[0].trigger_id == first.events[2].trigger_id
    assert first.captured[0].data == [0x90, 60, 127]
    assert source.events[4].tick == 5


def test_omit_active_drops_only_that_notes_controls_and_release() -> None:
    loop = plan_playback(
        sequence(),
        SequenceSelection(
            name='phrase',
            interval=TickRange(start=4, end=9),
            active_notes='omit_active',
        ),
    )[0]
    assert len(loop.events) == 1
    assert loop.events[0].trigger_id.endswith('-b')
    assert len(loop.cleanup) == 1


def test_note_at_end_is_excluded_and_release_at_start_is_ordered_after_retrigger() -> (
    None
):
    loop = plan_playback(
        sequence(), SequenceSelection(name='phrase', interval=TickRange(start=6, end=9))
    )[0]
    assert [e.kind for e in loop.events] == [
        'trigger',
        'trigger',
        'control_change',
        'release',
    ]
    assert len(loop.cleanup) == 1
    assert all(e.tick == 0 for e in loop.events)


@pytest.mark.parametrize(
    'event',
    [
        Trigger(tick=3, ordinal=3, part='piano', trigger_id='a', key=61),
        Release(tick=3, ordinal=3, part='piano', trigger_id='missing'),
        ControlChange(
            tick=3,
            ordinal=3,
            scope='trigger',
            part='piano',
            trigger_id='missing',
            control='bend',
            value=0,
        ),
    ],
)
def test_invalid_note_ownership_is_rejected(
    event: Trigger | Release | ControlChange,
) -> None:
    source = Sequence(timebase='clock', end=5, events=[*sequence().events[:3], event])
    with pytest.raises(ValueError):
        plan_playback(
            source, SequenceSelection(name='bad', interval=TickRange(start=0, end=5))
        )


def test_empty_sequence_and_invalid_selection() -> None:
    source = Sequence(timebase='clock', start=-10, end=10)
    loop = plan_playback(
        source, SequenceSelection(name='silence', interval=TickRange(start=-5, end=5))
    )[0]
    assert loop.events == loop.controls == loop.cleanup == loop.captured == []
    with pytest.raises(ValueError):
        plan_playback(
            source, SequenceSelection(name='bad', interval=TickRange(start=-11, end=5))
        )
    with pytest.raises(ValueError):
        state_at(source, True)


def test_portable_loop_example() -> None:
    import json
    from pathlib import Path

    case = json.loads(Path('conformance/sequence-playback.json').read_text())
    loops = plan_playback(
        Sequence.model_validate(case['sequence']),
        SequenceSelection.model_validate(case['selection']),
    )
    assert [
        dict(
            start=x.start,
            end=x.end,
            trigger_id=x.events[0].trigger_id,
            trigger_tick=x.events[0].tick,
            release_tick=x.cleanup[0].tick,
        )
        for x in loops
    ] == case['expected']


def test_reused_ids_and_independent_parts_keep_distinct_ownership() -> None:
    source = Sequence(
        timebase='clock',
        end=5,
        events=[
            Trigger(tick=0, ordinal=0, part='left', trigger_id='a', key=60),
            Trigger(tick=0, ordinal=1, part='right', trigger_id='a', key=60),
            Release(tick=1, ordinal=2, part='left', trigger_id='a'),
            Trigger(tick=2, ordinal=3, part='left', trigger_id='a', key=60),
        ],
    )
    loop = plan_playback(
        source, SequenceSelection(name='both', interval=TickRange(start=0, end=5))
    )[0]
    assert len(loop.events) == 4
    assert {e.part for e in loop.cleanup} == {'left', 'right'}


def test_control_snapshot_does_not_carry_later_changes_into_next_loop() -> None:
    source = Sequence(
        timebase='clock',
        end=5,
        events=[
            ControlChange(
                tick=2, ordinal=0, scope='instrument', control='gain', value=0.7
            ),
        ],
    )
    loops = plan_playback(
        source,
        SequenceSelection(
            name='reset', interval=TickRange(start=0, end=5), repetitions=2
        ),
    )
    assert loops[0].controls == loops[1].controls == []
    assert loops[0].events[0].tick == 2
    assert loops[1].events[0].tick == 7
