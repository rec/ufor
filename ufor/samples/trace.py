"""Portable semantic actions for prepared sample-instrument performances."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ..base import Identifier, Model, unique
from ..events import ControlChange, PerformanceEvent, Release, Trigger
from ..instrument_trace import (
    ActiveTrigger,
    ActiveVoice,
    ControlObservation,
    Diagnostic,
    LifecycleSnapshot,
    RetirementCause,
    VoiceRetirement,
)
from ..instrument_trace import (
    VoiceStart as LifecycleVoiceStart,
)
from ..modulation import ParameterValue
from . import enums
from .instrument import (
    SampleInstrument,
    SampleSlot,
    effective_selection,
    effective_settings,
)
from .processing import ChannelRoute, SoundSettings
from .selection import SelectionState, choose, random_range_value
from .variation import ResolvedVariation, resolve


class VoiceStart(LifecycleVoiceStart):
    slice: Identifier
    start_frame: int
    alignment_frames: int
    channels: list[ChannelRoute]
    settings: SoundSettings
    parameters: list[ParameterValue] = Field(default_factory=list)
    variation: ResolvedVariation = ResolvedVariation()


Action = Annotated[
    VoiceStart | VoiceRetirement | ControlObservation | Diagnostic,
    Field(discriminator='kind'),
]


class TraceSnapshot(LifecycleSnapshot):
    selection: SelectionState


class SemanticTrace(Model):
    seed: int = Field(strict=True, ge=0, lt=2**64)
    actions: list[Action] = Field(default_factory=list)
    snapshots: list[TraceSnapshot] = Field(default_factory=list)

    @model_validator(mode='after')
    def ordered_actions(self) -> Self:
        coordinates = [(a.tick, a.ordinal) for a in self.actions]
        if coordinates != sorted(coordinates):
            raise ValueError('trace actions must be ordered by tick and ordinal')
        unique(
            (a.voice_id for a in self.actions if isinstance(a, VoiceStart)),
            'voice ID',
        )
        return self


def prepare(
    instrument: SampleInstrument, events: list[PerformanceEvent], seed: int
) -> SemanticTrace:
    """Resolve selection, linked takes, releases, and chokes without rendering."""
    actions: list[Action] = []
    state = SelectionState(seed=seed)
    voices: list[ActiveVoice] = []
    triggers: list[ActiveTrigger] = []
    sustain: dict[Identifier, bool] = {}
    groups = {g.name: g for g in instrument.groups}
    slices = {s.name: s for s in instrument.slices}
    selections = {s.name: s for s in instrument.instrument.selections}
    playback_modes = {
        s.name: s.playback.mode or instrument.instrument.playback.mode
        for s in instrument.slots
    }

    def selected_slots(
        part: Identifier,
        kind: enums.TriggerKind,
        key: int,
        velocity: float,
        event: PerformanceEvent,
    ) -> list[SampleSlot]:
        nonlocal state
        random_value = random_range_value(
            seed, part, getattr(event, 'trigger_id', None), event.tick, event.ordinal
        )
        eligible = [
            s
            for s in instrument.slots
            if s.trigger == kind
            and s.mapping.lowest_key <= key <= s.mapping.highest_key
            and s.mapping.minimum_velocity <= velocity <= s.mapping.maximum_velocity
            and (s.random_range is None or s.random_range.contains(random_value))
            and (
                kind
                not in (
                    enums.TriggerKind.sustain_press,
                    enums.TriggerKind.sustain_release,
                )
                or s.mapping.event_key == key
            )
        ]
        selected = [
            s for s in eligible if effective_selection(s, groups.get(s.group)) is None
        ]
        for selection in selections.values():
            candidates = [
                s
                for s in eligible
                if effective_selection(s, groups.get(s.group)) == selection.name
            ]
            if candidates:
                choice, state = choose(
                    selection,
                    state,
                    part,
                    kind,
                    key,
                    sorted({s.take or s.name for s in candidates}),
                )
                selected.extend(s for s in candidates if (s.take or s.name) == choice)
        return selected

    def retire(
        voice: ActiveVoice,
        event: PerformanceEvent,
        cause: RetirementCause,
        action: Literal['release', 'stop', 'fade'],
        fade_seconds: float | None = None,
    ) -> None:
        actions.append(
            VoiceRetirement(
                tick=event.tick,
                ordinal=event.ordinal,
                voice_id=voice.voice_id,
                cause=cause,
                action=action,
                fade_seconds=fade_seconds,
            )
        )
        voices.remove(voice)

    def start_slots(
        slots: list[SampleSlot],
        event: PerformanceEvent,
        part: Identifier,
        trigger_id: Identifier | None,
        key: int,
        pitch_hz: float | None = None,
    ) -> None:
        for voice in list(voices):
            rules = [
                c
                for s in slots
                for c in s.chokes
                if voice.part == part and c.group == voice.choke_group
            ]
            if not rules:
                continue
            modes = {c.mode for c in rules}
            if enums.ChokeMode.immediate in modes:
                retire(voice, event, RetirementCause.choke, 'stop')
            elif modes == {enums.ChokeMode.release}:
                retire(voice, event, RetirementCause.choke, 'release')
            elif modes == {enums.ChokeMode.fade}:
                retire(
                    voice,
                    event,
                    RetirementCause.choke,
                    'fade',
                    min(c.fade_seconds for c in rules if c.fade_seconds is not None),
                )
            else:
                raise ValueError(
                    'combined fade and envelope-release chokes are unsupported'
                )
        policy = instrument.instrument.voice_policy
        if policy is not None and any(
            s.trigger == enums.TriggerKind.start for s in slots
        ):
            if len(slots) > policy.maximum_voices:
                raise ValueError('trigger batch exceeds maximum_voices')
            if policy.same_key != enums.SameKey.stack:
                for voice in [v for v in voices if v.part == part and v.key == key]:
                    action = (
                        'release'
                        if policy.same_key == enums.SameKey.release
                        else 'stop'
                    )
                    retire(voice, event, RetirementCause.same_key, action)
            while len(voices) + len(slots) > policy.maximum_voices:
                action = (
                    'release'
                    if policy.overflow == enums.VoiceOverflow.release_oldest
                    else 'stop'
                )
                retire(voices[0], event, RetirementCause.voice_limit, action)
        for slot in slots:
            voice_id = (
                f'voice-{part}-{trigger_id}-{slot.name}'
                if trigger_id is not None
                else f'voice-{part}-sustain-{event.tick}-{event.ordinal}-{slot.name}'
            )
            sample_slice = slices[slot.slice]
            resolved_variation = resolve(
                slot.variation,
                seed,
                part,
                trigger_id,
                event.tick,
                event.ordinal,
                (
                    slot.take
                    if trigger_id is not None and slot.take is not None
                    else slot.name
                ),
            )
            actions.append(
                VoiceStart(
                    tick=event.tick,
                    ordinal=event.ordinal,
                    voice_id=voice_id,
                    part=part,
                    trigger_id=trigger_id,
                    template=slot.name,
                    key=key,
                    pitch_hz=event.pitch_hz if isinstance(event, Trigger) else pitch_hz,
                    slice=slot.slice,
                    start_frame=sample_slice.start_frame + slot.alignment_frames,
                    alignment_frames=slot.alignment_frames,
                    channels=slot.channels,
                    settings=effective_settings(slot, groups.get(slot.group)),
                    variation=resolved_variation,
                )
            )
            voices.append(
                ActiveVoice(
                    voice_id=voice_id,
                    part=part,
                    trigger_id=trigger_id,
                    template=slot.name,
                    key=key,
                    template_trigger=slot.trigger,
                    choke_group=slot.choke_group,
                )
            )

    def start_sustain(
        kind: enums.TriggerKind, event: ControlChange, part: Identifier
    ) -> None:
        keys = {
            s.mapping.event_key
            for s in instrument.slots
            if s.trigger == kind and s.mapping.event_key is not None
        }
        for key in sorted(keys):
            start_slots(
                selected_slots(part, kind, key, event.value, event),
                event,
                part,
                None,
                key,
            )

    def update_trigger(trigger: ActiveTrigger, **changes: object) -> ActiveTrigger:
        updated = trigger.model_copy(update=changes)
        triggers[triggers.index(trigger)] = updated
        return updated

    def start_voices(trigger: ActiveTrigger) -> list[ActiveVoice]:
        return [
            voice
            for voice in voices
            if voice.part == trigger.part
            and voice.trigger_id == trigger.trigger_id
            and voice.template_trigger == enums.TriggerKind.start
        ]

    for event in sorted(events, key=lambda e: (e.tick, e.ordinal)):
        if isinstance(event, ControlChange):
            actions.append(
                ControlObservation(
                    tick=event.tick,
                    ordinal=event.ordinal,
                    control=event.control,
                    value=event.value,
                    scope=event.scope,
                    part=event.part,
                    trigger_id=event.trigger_id,
                )
            )
            sustain_definition = instrument.instrument.sustain
            if (
                sustain_definition is not None
                and event.scope == 'part'
                and event.control == sustain_definition.control
                and event.part is not None
            ):
                assert event.part is not None
                part = event.part
                was_pressed = sustain.get(
                    part,
                    instrument.instrument.controls[sustain_definition.control].default
                    >= sustain_definition.threshold,
                )
                is_pressed = event.value >= sustain_definition.threshold
                sustain[part] = is_pressed
                if not was_pressed and is_pressed:
                    start_sustain(enums.TriggerKind.sustain_press, event, part)
                elif was_pressed and not is_pressed:
                    for trigger in list(triggers):
                        if (
                            trigger.part == part
                            and trigger.physically_released
                            and not trigger.logical_released
                        ):
                            if start_voices(trigger):
                                start_slots(
                                    selected_slots(
                                        trigger.part,
                                        enums.TriggerKind.logical_release,
                                        trigger.key,
                                        trigger.velocity,
                                        event,
                                    ),
                                    event,
                                    trigger.part,
                                    trigger.trigger_id,
                                    trigger.key,
                                    trigger.pitch_hz,
                                )
                                for voice in list(start_voices(trigger)):
                                    if (
                                        playback_modes[voice.template]
                                        == enums.PlaybackMode.one_shot
                                    ):
                                        continue
                                    retire(
                                        voice,
                                        event,
                                        RetirementCause.logical_release,
                                        'release',
                                    )
                            update_trigger(trigger, logical_released=True)
                    start_sustain(enums.TriggerKind.sustain_release, event, part)
        elif isinstance(event, Release):
            trigger = next(
                (
                    t
                    for t in triggers
                    if t.part == event.part and t.trigger_id == event.trigger_id
                ),
                None,
            )
            if trigger is None:
                actions.append(
                    Diagnostic(
                        tick=event.tick,
                        ordinal=event.ordinal,
                        code='unknown-release',
                        message=f'No active trigger {event.trigger_id}',
                    )
                )
            elif not trigger.physically_released:
                trigger = update_trigger(trigger, physically_released=True)
                if start_voices(trigger):
                    start_slots(
                        selected_slots(
                            trigger.part,
                            enums.TriggerKind.release,
                            trigger.key,
                            trigger.velocity,
                            event,
                        ),
                        event,
                        trigger.part,
                        trigger.trigger_id,
                        trigger.key,
                        trigger.pitch_hz,
                    )
                pressed = sustain.get(
                    trigger.part,
                    instrument.instrument.sustain is not None
                    and instrument.instrument.controls[
                        instrument.instrument.sustain.control
                    ].default
                    >= instrument.instrument.sustain.threshold,
                )
                if not pressed:
                    if start_voices(trigger):
                        start_slots(
                            selected_slots(
                                trigger.part,
                                enums.TriggerKind.logical_release,
                                trigger.key,
                                trigger.velocity,
                                event,
                            ),
                            event,
                            trigger.part,
                            trigger.trigger_id,
                            trigger.key,
                            trigger.pitch_hz,
                        )
                        for voice in list(start_voices(trigger)):
                            if (
                                playback_modes[voice.template]
                                == enums.PlaybackMode.one_shot
                            ):
                                continue
                            retire(
                                voice,
                                event,
                                RetirementCause.logical_release,
                                'release',
                            )
                    update_trigger(trigger, logical_released=True)
        elif isinstance(event, Trigger):
            instrument.validate_event(event)
            selected = selected_slots(
                event.part,
                enums.TriggerKind.start,
                event.key,
                event.velocity,
                event,
            )
            triggers.append(
                ActiveTrigger(
                    part=event.part,
                    trigger_id=event.trigger_id,
                    key=event.key,
                    velocity=event.velocity,
                    pitch_hz=event.pitch_hz,
                    templates=[slot.name for slot in selected],
                )
            )
            start_slots(selected, event, event.part, event.trigger_id, event.key)
    return SemanticTrace(
        seed=seed,
        actions=actions,
        snapshots=[
            TraceSnapshot(
                tick=events[-1].tick if events else 0,
                ordinal=events[-1].ordinal if events else 0,
                selection=state,
                voices=voices,
                triggers=triggers,
            )
        ],
    )
