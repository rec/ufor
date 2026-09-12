"""Pure sequence selection and replay planning; never dispatches external actions."""

from typing import Literal

from pydantic import Field

from .base import Identifier, Model
from .events import ControlChange, PerformanceEvent, Release, StoredEvent, Trigger
from .sequence import Sequence
from .time import TickRange


class SequenceSelection(Model):
    name: Identifier
    interval: TickRange
    start: int = Field(default=0, strict=True)
    repetitions: int = Field(default=1, strict=True, ge=1)
    active_notes: Literal['retrigger_active', 'omit_active'] = 'retrigger_active'


class SequenceState(Model):
    """State immediately before a tick; absent controls retain declared defaults."""

    triggers: list[Trigger] = Field(default_factory=list)
    controls: list[ControlChange] = Field(default_factory=list)


class PlaybackIteration(Model):
    """Apply controls, events, then cleanup in order, even at a shared boundary."""

    name: Identifier
    iteration: int = Field(ge=0, strict=True)
    timebase: Identifier
    start: int = Field(strict=True)
    end: int = Field(strict=True)
    controls: list[ControlChange]
    events: list[PerformanceEvent]
    captured: list[StoredEvent]
    cleanup: list[Release]


def state_at(sequence: Sequence, tick: int) -> SequenceState:
    """Reconstruct semantic state before tick without replaying raw messages."""
    if type(tick) is not int or not sequence.start <= tick <= sequence.end:
        raise ValueError('seek tick must be an integer within the sequence extent')
    triggers: dict[tuple[str, str], Trigger] = {}
    controls: dict[tuple[str, str | None, str | None, str], ControlChange] = {}
    for event in sequence.events:
        if event.tick >= tick:
            break
        if isinstance(event, Trigger):
            key = (event.part, event.trigger_id)
            if key in triggers:
                raise ValueError('trigger ID is already active in this part')
            triggers[key] = event
        elif isinstance(event, Release):
            key = (event.part, event.trigger_id)
            if key not in triggers:
                raise ValueError('release has no active trigger')
            del triggers[key]
            controls = {
                k: v
                for k, v in controls.items()
                if not (v.scope == 'trigger' and (v.part, v.trigger_id) == key)
            }
        elif isinstance(event, ControlChange):
            if (
                event.scope == 'trigger'
                and (event.part, event.trigger_id) not in triggers
            ):
                raise ValueError('control change has no active trigger')
            controls[(event.scope, event.part, event.trigger_id, event.control)] = event
    return SequenceState(
        triggers=list(triggers.values()), controls=list(controls.values())
    )


def plan_playback(
    sequence: Sequence, selection: SequenceSelection
) -> list[PlaybackIteration]:
    """Crop/seek and repeat a half-open interval, with explicit note cleanup."""
    left, right = selection.interval.start, selection.interval.end
    if not sequence.start <= left < right <= sequence.end:
        raise ValueError('selection must lie within the sequence extent')
    # Validate ownership through the selected end, including the reconstruction prefix.
    state_at(sequence, right)
    initial = state_at(sequence, left)
    result: list[PlaybackIteration] = []
    for iteration in range(selection.repetitions):
        start = selection.start + iteration * (right - left)
        end = start + right - left
        prefix = f'clip-{len(selection.name)}-{selection.name}-{iteration}-'
        active: dict[tuple[str, str], Trigger] = {}
        events: list[PerformanceEvent] = []
        captured: list[StoredEvent] = []
        controls = [
            c.model_copy(update={'tick': start, 'ordinal': i})
            for i, c in enumerate(initial.controls)
            if c.scope != 'trigger'
        ]

        if selection.active_notes == 'retrigger_active':
            for trigger in initial.triggers:
                active[(trigger.part, trigger.trigger_id)] = trigger
                _append_event(events, trigger, start, prefix)
            for control in initial.controls:
                if control.scope == 'trigger':
                    _append_event(events, control, start, prefix)
        for event in sequence.events:
            if not left <= event.tick < right:
                continue
            tick = start + event.tick - left
            if isinstance(event, Trigger):
                active[(event.part, event.trigger_id)] = event
            elif isinstance(event, Release):
                if active.pop((event.part, event.trigger_id), None) is None:
                    continue  # Release of an intentionally omitted initial note.
            elif isinstance(event, ControlChange):
                if (
                    event.scope == 'trigger'
                    and (event.part, event.trigger_id) not in active
                ):
                    continue
            else:
                captured.append(event.model_copy(update={'tick': tick}))
                continue
            _append_event(events, event, tick, prefix)
        cleanup = [
            Release(
                tick=end,
                ordinal=len(events) + i,
                part=t.part,
                trigger_id=prefix + t.trigger_id,
            )
            for i, t in enumerate(active.values())
        ]
        result.append(
            PlaybackIteration(
                name=selection.name,
                iteration=iteration,
                timebase=sequence.timebase,
                start=start,
                end=end,
                controls=controls,
                events=events,
                captured=captured,
                cleanup=cleanup,
            )
        )
    return result


def _append_event(
    events: list[PerformanceEvent], event: PerformanceEvent, tick: int, prefix: str
) -> None:
    updates: dict[str, object] = {'tick': tick, 'ordinal': len(events)}
    if isinstance(event, (Trigger, Release)) or event.scope == 'trigger':
        updates['trigger_id'] = prefix + str(event.trigger_id)
    events.append(event.model_copy(update=updates))
