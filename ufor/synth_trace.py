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
    TriggerContext,
    VoiceRetirement,
)
from .instrument_trace import (
    VoiceStart as LifecycleVoiceStart,
)
from .noise import stream_key
from .oscillator import Oscillator
from .samples import enums
from .samples.processing import ChannelRoute
from .synth import FMVoice, NoiseVoice, SynthInstrument, SynthVoice


class VoiceStart(LifecycleVoiceStart):
    oscillator: Oscillator | None = None
    channels: list[ChannelRoute]
    settings: SynthVoice | FMVoice | NoiseVoice

    noise_key: int | None = Field(
        default=None, strict=True, ge=0, lt=2**64, exclude_if=lambda v: v is None
    )

    @model_validator(mode='after')
    def source_matches_settings(self) -> Self:
        expected = (
            self.settings.oscillator if isinstance(self.settings, SynthVoice) else None
        )
        if isinstance(self.settings, NoiseVoice) != (self.noise_key is not None):
            raise ValueError(
                'Noise starts require a stream key; other sources forbid it'
            )
        if self.oscillator != expected:
            raise ValueError('Voice start oscillator must match its source settings')
        return self


Action = Annotated[
    VoiceStart | VoiceRetirement | TriggerContext | ControlObservation | Diagnostic,
    Field(discriminator='kind'),
]


class SynthTrace(Model):
    seed: int = Field(strict=True, ge=0, lt=2**64)
    actions: list[Action] = Field(default_factory=list)
    snapshots: list[LifecycleSnapshot] = Field(default_factory=list)

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
) -> SynthTrace:
    """Resolve synth voice lifecycle without rendering audio."""
    instrument = SynthInstrument.model_validate(instrument.model_dump())
    if instrument.articulations is not None:
        raise ValueError('articulation preparation is unsupported')
    events = sorted(events, key=lambda e: (e.tick, e.ordinal))
    unique(((e.tick, e.ordinal) for e in events), 'event coordinate')
    actions: list[Action] = []
    voices: list[ActiveVoice] = []
    triggers: list[ActiveTrigger] = []
    sustain: dict[Identifier, bool] = {}
    next_voice = 0

    def selected_voices(
        kind: enums.TriggerKind, key: int, velocity: float
    ) -> list[SynthVoice | FMVoice | NoiseVoice]:
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

    def start_voices(
        selected: list[SynthVoice | FMVoice | NoiseVoice],
        event: PerformanceEvent,
        part: Identifier,
        trigger_id: Identifier | None,
        key: int,
        pitch_hz: float | None = None,
    ) -> None:
        nonlocal next_voice
        pitch_hz = event.pitch_hz if isinstance(event, Trigger) else pitch_hz
        for voice in list(voices):
            rules = [
                c
                for s in selected
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
        policy = instrument.voice_policy
        if policy is not None and any(
            s.trigger == enums.TriggerKind.start for s in selected
        ):
            if len(selected) > policy.maximum_voices:
                raise ValueError('trigger batch exceeds maximum_voices')
            if policy.same_key != enums.SameKey.stack:
                for voice in [v for v in voices if v.part == part and v.key == key]:
                    action = (
                        'release'
                        if policy.same_key == enums.SameKey.release
                        else 'stop'
                    )
                    retire(voice, event, RetirementCause.same_key, action)
            while len(voices) + len(selected) > policy.maximum_voices:
                action = (
                    'release'
                    if policy.overflow == enums.VoiceOverflow.release_oldest
                    else 'stop'
                )
                retire(voices[0], event, RetirementCause.voice_limit, action)
        for template in selected:
            voice_id = f'voice-{next_voice}'
            next_voice += 1
            actions.append(
                VoiceStart(
                    tick=event.tick,
                    ordinal=event.ordinal,
                    voice_id=voice_id,
                    part=part,
                    trigger_id=trigger_id,
                    template=template.name,
                    key=key,
                    pitch_hz=(
                        pitch_hz + template.frequency_offset_hz
                        if pitch_hz is not None
                        else None
                    ),
                    oscillator=template.oscillator
                    if isinstance(template, SynthVoice)
                    else None,
                    channels=template.channels,
                    settings=template,
                    noise_key=stream_key(seed, voice_id)
                    if isinstance(template, NoiseVoice)
                    else None,
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

    for event in events:
        instrument.validate_event(event)
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
                                    trigger.pitch_hz,
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
                        trigger.pitch_hz,
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
                            trigger.pitch_hz,
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
            previous = next(
                (
                    t
                    for t in triggers
                    if (t.part, t.trigger_id) == (event.part, event.trigger_id)
                ),
                None,
            )
            if previous is not None:
                if not previous.logical_released or any(
                    (v.part, v.trigger_id) == (event.part, event.trigger_id)
                    for v in voices
                ):
                    raise ValueError('trigger ID is still active in this part')
                triggers.remove(previous)
            actions.append(
                TriggerContext(
                    tick=event.tick,
                    ordinal=event.ordinal,
                    part=event.part,
                    trigger_id=event.trigger_id,
                    velocity=event.velocity,
                    controls={n: c.default for n, c in instrument.controls.items()}
                    | event.controls,
                )
            )
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
    return SynthTrace(
        seed=seed,
        actions=actions,
        snapshots=[
            LifecycleSnapshot(
                tick=events[-1].tick if events else 0,
                ordinal=events[-1].ordinal if events else 0,
                voices=voices,
                triggers=triggers,
            )
        ],
    )
