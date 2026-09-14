"""Portable semantic actions for prepared synth-instrument performances."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .base import Identifier, Model, unique
from .events import ControlChange, PerformanceEvent, Release, Trigger
from .instrument_trace import (
    ActiveTrigger,
    ActiveVoice,
    ControlObservation,
    Diagnostic,
    LifecycleSnapshot,
    RetirementCause,
    VoiceRetirement,
)
from .instrument_trace import (
    VoiceStart as LifecycleVoiceStart,
)
from .oscillator import Oscillator
from .samples import enums
from .samples.processing import ChannelRoute, SoundSettings
from .synth import SynthInstrument, SynthVoice


class VoiceStart(LifecycleVoiceStart):
    oscillator: Oscillator
    channels: list[ChannelRoute]
    settings: SoundSettings


Action = Annotated[
    VoiceStart | VoiceRetirement | ControlObservation | Diagnostic,
    Field(discriminator='kind'),
]


class TraceSnapshot(LifecycleSnapshot):
    pass


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
    instrument: SynthInstrument, events: list[PerformanceEvent], seed: int
) -> SemanticTrace:
    """Resolve synth voice lifecycle without rendering audio."""
    actions: list[Action] = []
    voices: list[ActiveVoice] = []
    triggers: list[ActiveTrigger] = []
    sustain: dict[Identifier, bool] = {}

    def selected_voices(
        kind: enums.TriggerKind, key: int, velocity: float
    ) -> list[SynthVoice]:
        return [
            voice
            for voice in instrument.voices
            if voice.trigger == kind
            and voice.mapping.lowest_key <= key <= voice.mapping.highest_key
            and voice.mapping.minimum_velocity
            <= velocity
            <= voice.mapping.maximum_velocity
            and (
                kind
                not in (
                    enums.TriggerKind.sustain_press,
                    enums.TriggerKind.sustain_release,
                )
                or voice.mapping.event_key == key
            )
        ]

    def retire(
        voice: ActiveVoice,
        event: PerformanceEvent,
        cause: RetirementCause,
        action: Literal['release', 'stop'],
    ) -> None:
        actions.append(
            VoiceRetirement(
                tick=event.tick,
                ordinal=event.ordinal,
                voice_id=voice.voice_id,
                cause=cause,
                action=action,
            )
        )
        voices.remove(voice)

    def start_voices(
        selected: list[SynthVoice],
        event: PerformanceEvent,
        part: Identifier,
        trigger_id: Identifier | None,
        key: int,
    ) -> None:
        for template in selected:
            for voice in list(voices):
                if voice.choke_group in {c.group for c in template.chokes}:
                    retire(voice, event, RetirementCause.choke, 'stop')
        for template in selected:
            if template.trigger == enums.TriggerKind.start:
                policy = instrument.voice_policy
                if policy is not None:
                    same_key = [v for v in voices if v.part == part and v.key == key]
                    if policy.same_key != enums.SameKey.stack:
                        action = (
                            'release'
                            if policy.same_key == enums.SameKey.release
                            else 'stop'
                        )
                        for voice in same_key:
                            retire(voice, event, RetirementCause.same_key, action)
                    while len(voices) >= policy.maximum_voices:
                        voice = voices[0]
                        action = (
                            'release'
                            if policy.overflow == enums.VoiceOverflow.release_oldest
                            else 'stop'
                        )
                        retire(voice, event, RetirementCause.voice_limit, action)
            voice_id = (
                f'voice-{part}-{trigger_id}-{template.name}'
                if trigger_id is not None
                else (
                    f'voice-{part}-sustain-{event.tick}-{event.ordinal}-{template.name}'
                )
            )
            actions.append(
                VoiceStart(
                    tick=event.tick,
                    ordinal=event.ordinal,
                    voice_id=voice_id,
                    part=part,
                    trigger_id=trigger_id,
                    template=template.name,
                    key=key,
                    pitch_hz=(event.pitch_hz if isinstance(event, Trigger) else None),
                    oscillator=template.oscillator,
                    channels=template.channels,
                    settings=template,
                )
            )
            voices.append(
                ActiveVoice(
                    voice_id=voice_id,
                    part=part,
                    trigger_id=trigger_id,
                    template=template.name,
                    key=key,
                    template_trigger=template.trigger,
                    choke_group=template.choke_group,
                )
            )

    def start_sustain(
        kind: enums.TriggerKind, event: ControlChange, part: Identifier
    ) -> None:
        keys = {
            voice.mapping.event_key
            for voice in instrument.voices
            if voice.trigger == kind and voice.mapping.event_key is not None
        }
        for key in sorted(keys):
            start_voices(
                selected_voices(kind, key, event.value), event, part, None, key
            )

    def update_trigger(trigger: ActiveTrigger, **changes: object) -> ActiveTrigger:
        updated = trigger.model_copy(update=changes)
        triggers[triggers.index(trigger)] = updated
        return updated

    def start_template_voices(trigger: ActiveTrigger) -> list[ActiveVoice]:
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
            sustain_definition = instrument.sustain
            if (
                sustain_definition is not None
                and event.scope == 'part'
                and event.control == sustain_definition.control
                and event.part is not None
            ):
                part = event.part
                was_pressed = sustain.get(
                    part,
                    instrument.controls[sustain_definition.control].default
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
                            if start_template_voices(trigger):
                                start_voices(
                                    selected_voices(
                                        enums.TriggerKind.logical_release,
                                        trigger.key,
                                        trigger.velocity,
                                    ),
                                    event,
                                    trigger.part,
                                    trigger.trigger_id,
                                    trigger.key,
                                )
                                for voice in list(start_template_voices(trigger)):
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
                if start_template_voices(trigger):
                    start_voices(
                        selected_voices(
                            enums.TriggerKind.release, trigger.key, trigger.velocity
                        ),
                        event,
                        trigger.part,
                        trigger.trigger_id,
                        trigger.key,
                    )
                pressed = sustain.get(
                    trigger.part,
                    instrument.sustain is not None
                    and instrument.controls[instrument.sustain.control].default
                    >= instrument.sustain.threshold,
                )
                if not pressed:
                    if start_template_voices(trigger):
                        start_voices(
                            selected_voices(
                                enums.TriggerKind.logical_release,
                                trigger.key,
                                trigger.velocity,
                            ),
                            event,
                            trigger.part,
                            trigger.trigger_id,
                            trigger.key,
                        )
                        for voice in list(start_template_voices(trigger)):
                            retire(
                                voice,
                                event,
                                RetirementCause.logical_release,
                                'release',
                            )
                    update_trigger(trigger, logical_released=True)
        elif isinstance(event, Trigger):
            instrument.validate_event(event)
            selected = selected_voices(
                enums.TriggerKind.start, event.key, event.velocity
            )
            triggers.append(
                ActiveTrigger(
                    part=event.part,
                    trigger_id=event.trigger_id,
                    key=event.key,
                    velocity=event.velocity,
                    pitch_hz=event.pitch_hz,
                    templates=[voice.name for voice in selected],
                )
            )
            start_voices(selected, event, event.part, event.trigger_id, event.key)
    return SemanticTrace(
        seed=seed,
        actions=actions,
        snapshots=[
            TraceSnapshot(
                tick=events[-1].tick if events else 0,
                ordinal=events[-1].ordinal if events else 0,
                voices=voices,
                triggers=triggers,
            )
        ],
    )
