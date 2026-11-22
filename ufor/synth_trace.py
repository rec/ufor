"""Portable semantic actions for prepared synth-instrument performances."""

from collections.abc import Callable
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .base import Identifier, Model, UnitInterval, unique
from .command_schedule import ScheduleCommands, schedule_commands
from .control import TempoMap
from .events import (
    ControlChange,
    EnvelfoChange,
    LFOChange,
    PerformanceEvent,
    Release,
    Trigger,
)
from .instrument_trace import (
    ActiveTrigger,
    ActiveVoice,
    ControlObservation,
    Diagnostic,
    EnvelfoObservation,
    LFOObservation,
    LifecycleSnapshot,
    RetirementCause,
    TriggerContext,
    TriggerRelease,
    VoiceRetirement,
)
from .instrument_trace import (
    VoiceStart as LifecycleVoiceStart,
)
from .oscillator import Oscillator
from .samples import enums
from .samples.processing import ChannelRoute
from .synth import (
    NoiseVoice,
    SynthInstrument,
    SynthSource,
    SynthVoice,
    YamahaVoiceTemplate,
)
from .voice_admission import VoiceAdmission, plan_retirements
from .voice_release import (
    KeyRelease,
    PedalChange,
    ReleasePlan,
    ReleaseRequest,
    plan_release,
)
from .voice_start import PrepareVoiceStart, prepare_values


class VoiceStart(LifecycleVoiceStart):
    oscillator: Oscillator | None = None
    channels: list[ChannelRoute]
    settings: SynthSource
    velocity: UnitInterval | None = Field(default=None, exclude_if=lambda v: v is None)

    noise_key: int | None = Field(
        default=None, strict=True, ge=0, lt=2**64, exclude_if=lambda v: v is None
    )

    @model_validator(mode='after')
    def source_matches_settings(self) -> Self:
        if isinstance(self.settings, YamahaVoiceTemplate) != (
            self.velocity is not None
        ):
            raise ValueError(
                'Yamaha starts require velocity; other synth starts forbid it'
            )
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
    VoiceStart
    | VoiceRetirement
    | TriggerContext
    | TriggerRelease
    | ControlObservation
    | LFOObservation
    | EnvelfoObservation
    | Diagnostic,
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


def matching_voices(
    voices: list[SynthSource],
    kind: enums.TriggerKind,
    key: int,
    velocity: float,
) -> list[SynthSource]:
    """Return all mapped voices in declaration order."""
    return [
        v
        for v in voices
        if v.trigger == kind
        and v.mapping.lowest_key <= key <= v.mapping.highest_key
        and v.mapping.minimum_velocity <= velocity <= v.mapping.maximum_velocity
        and (
            kind
            not in (enums.TriggerKind.sustain_press, enums.TriggerKind.sustain_release)
            or v.mapping.event_key == key
        )
    ]


def prepare(
    instrument: SynthInstrument,
    events: list[PerformanceEvent],
    seed: int,
    tempo_map: TempoMap | None = None,
    sample_rate: int | None = None,
    *,
    admit_voices: Callable[[VoiceAdmission], list[VoiceRetirement]] = plan_retirements,
    release_plan: Callable[[ReleaseRequest], ReleasePlan] = plan_release,
    eligible_voices: Callable[[enums.TriggerKind, int, float], list[Identifier]]
    | None = None,
    prepare_start: PrepareVoiceStart = prepare_values,
    schedule: ScheduleCommands = schedule_commands,
    validate_event: Callable[[PerformanceEvent], None] | None = None,
) -> SynthTrace:
    """Resolve synth voice lifecycle without rendering audio."""
    instrument = SynthInstrument.model_validate(instrument.model_dump())
    validate_event = validate_event or instrument.validate_event
    if instrument.articulations is not None:
        raise ValueError('articulation preparation is unsupported')
    events = sorted(events, key=lambda e: (e.tick, e.ordinal))
    unique(((e.tick, e.ordinal) for e in events), 'event coordinate')
    if any(
        isinstance(e, EnvelfoChange) and e.quantize_beats is not None for e in events
    ):
        if tempo_map is None or type(sample_rate) is not int or sample_rate <= 0:
            raise ValueError(
                'quantized Envelfo commands require a host tempo map and sample rate'
            )
        coordinates = []
        for event in events:
            division = (
                event.quantize_beats if isinstance(event, EnvelfoChange) else None
            )
            if division is not None:
                validate_event(event)
            coordinates.append((event.tick, event.ordinal, division))
        scheduled: list[PerformanceEvent] = []
        for index, tick, ordinal in schedule(tempo_map, sample_rate, coordinates):
            event = events[index]
            if (tick, ordinal) != (event.tick, event.ordinal):
                event = event.model_copy(update={'tick': tick, 'ordinal': ordinal})
            scheduled.append(event)
        events = scheduled
    actions: list[Action] = []
    voices: list[ActiveVoice] = []
    triggers: list[ActiveTrigger] = []
    sustain: dict[Identifier, bool] = {}
    sustain_definition = instrument.sustain
    initially_pressed = (
        sustain_definition is not None
        and instrument.controls[sustain_definition.control].default
        >= sustain_definition.threshold
    )
    next_voice = 0
    voices_by_name = {v.name: v for v in instrument.voices}
    requires_admission = bool(
        instrument.voice_policy or any(s.chokes for s in instrument.voices)
    )

    def selected_voices(
        kind: enums.TriggerKind, key: int, velocity: float
    ) -> list[SynthSource]:
        if eligible_voices is None:
            return matching_voices(instrument.voices, kind, key, velocity)
        return [voices_by_name[n] for n in eligible_voices(kind, key, velocity)]

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
        selected: list[SynthSource],
        event: PerformanceEvent,
        part: Identifier,
        trigger_id: Identifier | None,
        key: int,
        pitch_hz: float | None = None,
        velocity: float = 1,
    ) -> None:
        nonlocal next_voice
        pitch_hz = event.pitch_hz if isinstance(event, Trigger) else pitch_hz
        velocity = event.velocity if isinstance(event, Trigger) else velocity
        if selected and requires_admission:
            retirements = admit_voices(
                VoiceAdmission(
                    tick=event.tick,
                    ordinal=event.ordinal,
                    part=part,
                    key=key,
                    voices=voices,
                    chokes=[c for s in selected for c in s.chokes],
                    count=len(selected),
                    policy=instrument.voice_policy
                    if any(s.trigger == enums.TriggerKind.start for s in selected)
                    else None,
                )
            )
            if retirements:
                actions.extend(retirements)
                retired = {r.voice_id for r in retirements}
                voices[:] = [v for v in voices if v.voice_id not in retired]
        for template in selected:
            voice_id = f'voice-{next_voice}'
            next_voice += 1
            voice_pitch, envelfo_key, noise_key = prepare_start(
                seed,
                voice_id,
                pitch_hz,
                template.frequency_offset_hz,
                isinstance(template, NoiseVoice),
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
                    pitch_hz=voice_pitch,
                    oscillator=template.oscillator
                    if isinstance(template, SynthVoice)
                    else None,
                    channels=template.channels,
                    settings=template,
                    velocity=velocity
                    if isinstance(template, YamahaVoiceTemplate)
                    else None,
                    noise_key=noise_key,
                    envelfo_key=envelfo_key,
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
                selected_voices(kind, key, event.value),
                event,
                part,
                None,
                key,
                velocity=event.value,
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

    def release_logically(index: int, event: PerformanceEvent) -> None:
        trigger = triggers[index]
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
                trigger.velocity,
            )
            for voice in start_template_voices(trigger):
                retire(voice, event, RetirementCause.logical_release, 'release')
        update_trigger(trigger, logical_released=True)

    for event in events:
        validate_event(event)
        if isinstance(event, LFOChange):
            actions.append(
                LFOObservation(
                    tick=event.tick,
                    ordinal=event.ordinal,
                    name=event.name,
                    action=event.action,
                    rate=event.rate,
                    position=event.position,
                    offset=event.offset,
                )
            )
        elif isinstance(event, EnvelfoChange):
            actions.append(
                EnvelfoObservation(
                    tick=event.tick,
                    ordinal=event.ordinal,
                    name=event.name,
                    target=event.target,
                    op=event.op,
                    part=event.part,
                    trigger_id=event.trigger_id,
                    action=event.action,
                    position=event.position,
                    offset=event.offset,
                )
            )
        elif isinstance(event, ControlChange):
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
            if (
                sustain_definition is not None
                and event.scope == 'part'
                and event.control == sustain_definition.control
                and event.part is not None
            ):
                part = event.part
                plan = release_plan(
                    ReleaseRequest(
                        triggers=triggers,
                        event=PedalChange(
                            part=part,
                            was_pressed=sustain.get(part, initially_pressed),
                            value=event.value,
                            threshold=sustain_definition.threshold,
                        ),
                    )
                )
                assert plan.sustain_pressed is not None
                sustain[part] = plan.sustain_pressed
                for index in plan.logical_indices:
                    release_logically(index, event)
                if plan.sustain_trigger is not None:
                    start_sustain(plan.sustain_trigger, event, part)
        elif isinstance(event, Release):
            plan = release_plan(
                ReleaseRequest(
                    triggers=triggers,
                    event=KeyRelease(
                        part=event.part,
                        trigger_id=event.trigger_id,
                        sustain_pressed=sustain.get(event.part, initially_pressed),
                    ),
                )
            )
            if plan.unknown_release:
                actions.append(
                    Diagnostic(
                        tick=event.tick,
                        ordinal=event.ordinal,
                        code='unknown-release',
                        message=f'No active trigger {event.trigger_id}',
                    )
                )
            elif plan.physical_index is not None:
                trigger = triggers[plan.physical_index]
                actions.append(
                    TriggerRelease(
                        tick=event.tick,
                        ordinal=event.ordinal,
                        part=event.part,
                        trigger_id=event.trigger_id,
                    )
                )
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
                        trigger.velocity,
                    )
                for index in plan.logical_indices:
                    release_logically(index, event)
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
