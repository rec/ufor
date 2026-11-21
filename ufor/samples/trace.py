"""Portable semantic actions for prepared sample-instrument performances."""

from collections import Counter
from collections.abc import Callable
from typing import Annotated, Literal, Self, TypedDict

from pydantic import Field, model_validator
from reccy.configuration import units

from ..base import Identifier, Model, unique
from ..events import (
    ControlChange,
    EnvelfoChange,
    LFOChange,
    PerformanceEvent,
    Release,
    Trigger,
)
from ..instrument_trace import (
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
from ..instrument_trace import (
    VoiceStart as LifecycleVoiceStart,
)
from ..modulation import ParameterValue
from ..voice_admission import VoiceAdmission, plan_retirements
from ..voice_release import (
    KeyRelease,
    PedalChange,
    ReleasePlan,
    ReleaseRequest,
    plan_release,
)
from ..voice_start import PrepareVoiceStart, prepare_values
from . import enums
from .instrument import (
    ResolvedSlotSettings,
    SampleInstrument,
    SampleSlot,
    resolve_slots,
)
from .processing import ChannelRoute, SoundSettings
from .selection import AdvanceSelection, SelectionState, choose, random_range_value
from .variation import ResolvedVariation, Variation, resolve


class VoiceStart(LifecycleVoiceStart):
    velocity: float = Field(default=1, ge=0, le=1)
    slice: Identifier
    start_frame: Annotated[int, units.unit_validator('frame')]
    alignment_frames: Annotated[int, units.unit_validator('frame')]
    channels: list[ChannelRoute]
    settings: SoundSettings
    parameters: list[ParameterValue] = Field(default_factory=list)
    variation: ResolvedVariation = ResolvedVariation()


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


class SampleSnapshot(LifecycleSnapshot):
    selection: SelectionState


class SampleTrace(Model):
    seed: int = Field(strict=True, ge=0, lt=2**64)
    actions: list[Action] = Field(default_factory=list)
    snapshots: list[SampleSnapshot] = Field(default_factory=list)

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


class EligibilityContext(TypedDict):
    """Event facts needed to evaluate slot eligibility."""

    trigger: enums.TriggerKind
    key: int | None
    velocity: float
    active_articulation: Identifier | None
    held_keys: list[int]
    previous_key: int | None
    controls: dict[Identifier, float]
    control_event: tuple[Identifier, float] | None
    note_on_count: int
    random_value: float


def matching_slots(
    slots: list[SampleSlot], context: EligibilityContext
) -> list[SampleSlot]:
    """Filter slots in declaration order against resolved event facts."""
    kind, key, velocity = context['trigger'], context['key'], context['velocity']
    control_event = context['control_event']
    held_keys = set(context['held_keys'])
    return [
        s
        for s in slots
        if s.trigger == kind
        and (key is None or s.mapping.lowest_key <= key <= s.mapping.highest_key)
        and (
            key is None
            or s.mapping.minimum_velocity <= velocity <= s.mapping.maximum_velocity
        )
        and (
            s.control_trigger is None
            or control_event is not None
            and s.control_trigger.control == control_event[0]
            and s.control_trigger.minimum_value
            <= control_event[1]
            <= s.control_trigger.maximum_value
        )
        and (not s.articulations or context['active_articulation'] in s.articulations)
        and all((c.key in held_keys) == c.pressed for c in s.key_conditions)
        and (s.previous_key is None or context['previous_key'] == s.previous_key)
        and all(
            c.minimum_value <= context['controls'][c.control] <= c.maximum_value
            for c in s.control_conditions
        )
        and (
            s.sequence is None
            or (context['note_on_count'] - 1) % s.sequence.length + 1
            == s.sequence.position
        )
        and (s.random_range is None or s.random_range.contains(context['random_value']))
        and (
            kind
            not in (enums.TriggerKind.sustain_press, enums.TriggerKind.sustain_release)
            or s.mapping.event_key == key
        )
    ]


def prepare(
    instrument: SampleInstrument,
    events: list[PerformanceEvent],
    seed: int,
    *,
    eligible_slots: Callable[[EligibilityContext], list[Identifier]] | None = None,
    advance_selection: AdvanceSelection | None = None,
    admit_voices: Callable[[VoiceAdmission], list[VoiceRetirement]] = plan_retirements,
    release_plan: Callable[[ReleaseRequest], ReleasePlan] = plan_release,
    prepare_start: PrepareVoiceStart = prepare_values,
    slot_settings: Callable[
        [SampleInstrument], dict[Identifier, ResolvedSlotSettings]
    ] = resolve_slots,
    draw_random_range: Callable[
        [int, str, str | None, int, int], float
    ] = random_range_value,
    resolve_variation: Callable[
        [Variation, int, Identifier, Identifier | None, int, int, Identifier],
        ResolvedVariation,
    ] = resolve,
) -> SampleTrace:
    """Resolve selection, linked takes, releases, and chokes without rendering.

    An optional eligibility evaluator returns matching slot names in declaration
    order. An optional selection evaluator advances a single take partition.
    The supplied draw functions resolve stateless event and per-voice values.
    This function owns event state and the order of partitions in snapshots.
    """
    instrument = SampleInstrument.model_validate(instrument.model_dump())
    articulations = instrument.settings.articulations
    if articulations is not None:
        if articulations.controls:
            raise ValueError('control-driven articulations are unsupported')
        if any(k.behavior != enums.KeyBehavior.latched for k in articulations.keys):
            raise ValueError('momentary keyswitches are unsupported')
    events = sorted(events, key=lambda e: (e.tick, e.ordinal))
    unique(((e.tick, e.ordinal) for e in events), 'event coordinate')
    actions: list[Action] = []
    state = SelectionState(seed=seed)
    voices: list[ActiveVoice] = []
    triggers: list[ActiveTrigger] = []
    sustain: dict[Identifier, bool] = {}
    next_voice = 0
    resolved_slots = slot_settings(instrument)
    pools = {p.name: p.policy for p in instrument.voice_pools}
    slot_pools = {s.name: s.voice_pool for s in instrument.slots}
    requires_admission = bool(
        pools
        or instrument.settings.voice_policy
        or any(s.chokes for s in instrument.slots)
    )
    slices = {s.name: s for s in instrument.slices}
    selections = {s.name: s for s in instrument.settings.selections}
    slots_by_name = {s.name: s for s in instrument.slots}
    control_defaults = {n: c.default for n, c in instrument.settings.controls.items()}
    sustain_definition = instrument.settings.sustain
    initially_pressed = (
        sustain_definition is not None
        and control_defaults[sustain_definition.control] >= sustain_definition.threshold
    )
    playback_modes = {
        s.name: s.playback.mode or instrument.settings.playback.mode
        for s in instrument.slots
    }

    def selected_slots(
        part: Identifier,
        kind: enums.TriggerKind,
        key: int | None,
        velocity: float,
        event: PerformanceEvent,
    ) -> list[SampleSlot]:
        nonlocal state
        articulations = instrument.settings.articulations
        active = (
            state.articulations.get(part, articulations.default)
            if articulations is not None
            else None
        )
        controls = state.controls.get(part, {})
        if isinstance(event, Trigger):
            controls = controls | event.controls
        context = EligibilityContext(
            trigger=kind,
            key=key,
            velocity=velocity,
            active_articulation=active,
            held_keys=list(state.held_keys.get(part, {}).values()),
            previous_key=state.previous_keys.get(part),
            controls=control_defaults | controls,
            control_event=(event.control, event.value)
            if isinstance(event, ControlChange)
            else None,
            note_on_count=state.note_on_counts.get(part, 0),
            random_value=draw_random_range(
                seed,
                part,
                getattr(event, 'trigger_id', None),
                event.tick,
                event.ordinal,
            ),
        )
        eligible = (
            matching_slots(instrument.slots, context)
            if eligible_slots is None
            else [slots_by_name[n] for n in eligible_slots(context)]
        )
        selected = [s for s in eligible if resolved_slots[s.name].selection is None]
        for selection in selections.values():
            candidates = [
                s
                for s in eligible
                if resolved_slots[s.name].selection == selection.name
            ]
            if candidates:
                assert key is not None
                choice, state = choose(
                    selection,
                    state,
                    part,
                    kind,
                    key,
                    sorted({s.take or s.name for s in candidates}),
                    advance=advance_selection,
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
        key: int | None,
        pitch_hz: float | None = None,
        velocity: float = 1,
    ) -> None:
        nonlocal next_voice
        if slots and requires_admission:
            retirements = admit_voices(
                VoiceAdmission(
                    tick=event.tick,
                    ordinal=event.ordinal,
                    part=part,
                    key=key,
                    voices=voices,
                    chokes=[c for s in slots for c in s.chokes],
                    count=len(slots),
                    policy=instrument.settings.voice_policy
                    if any(
                        s.trigger
                        in (enums.TriggerKind.start, enums.TriggerKind.control)
                        for s in slots
                    )
                    else None,
                    pool_counts=dict(
                        Counter(s.voice_pool for s in slots if s.voice_pool is not None)
                    ),
                    pools=pools,
                    pool_by_template=slot_pools,
                )
            )
            if retirements:
                actions.extend(retirements)
                retired = {r.voice_id for r in retirements}
                voices[:] = [v for v in voices if v.voice_id not in retired]
        for slot in slots:
            voice_velocity = event.velocity if isinstance(event, Trigger) else velocity
            voice_pitch = event.pitch_hz if isinstance(event, Trigger) else pitch_hz
            if slot.control_trigger is not None:
                voice_velocity = slot.control_trigger.velocity
                voice_pitch = slot.control_trigger.pitch_hz
            voice_id = f'voice-{next_voice}'
            next_voice += 1
            voice_pitch, envelfo_key, _ = prepare_start(
                seed, voice_id, voice_pitch, 0.0, False
            )
            sample_slice = slices[slot.slice]
            resolved_variation = resolve_variation(
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
                    velocity=voice_velocity,
                    pitch_hz=voice_pitch,
                    slice=slot.slice,
                    start_frame=sample_slice.start_frame + slot.alignment_frames,
                    alignment_frames=slot.alignment_frames,
                    channels=slot.channels,
                    settings=resolved_slots[slot.name].settings,
                    variation=resolved_variation,
                    envelfo_key=envelfo_key,
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
                velocity=event.value,
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

    def release_logically(index: int, event: PerformanceEvent) -> None:
        trigger = triggers[index]
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
                velocity=trigger.velocity,
            )
            for voice in start_voices(trigger):
                if playback_modes[voice.template] != enums.PlaybackMode.one_shot:
                    retire(voice, event, RetirementCause.logical_release, 'release')
        update_trigger(trigger, logical_released=True)

    for event in events:
        instrument.validate_event(event)
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
            if event.scope == 'part' and event.part is not None:
                state = state.model_copy(
                    update={
                        'controls': state.controls
                        | {
                            event.part: state.controls.get(event.part, {})
                            | {event.control: event.value}
                        }
                    }
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
            if event.scope == 'part' and event.part is not None:
                start_slots(
                    selected_slots(
                        event.part, enums.TriggerKind.control, None, 1, event
                    ),
                    event,
                    event.part,
                    None,
                    None,
                )
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
                if any(s.key_conditions for s in instrument.slots):
                    held = dict(state.held_keys.get(trigger.part, {}))
                    held.pop(trigger.trigger_id, None)
                    state = state.model_copy(
                        update={'held_keys': state.held_keys | {trigger.part: held}}
                    )
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
                        velocity=trigger.velocity,
                    )
                for index in plan.logical_indices:
                    release_logically(index, event)
        elif isinstance(event, Trigger):
            switches = instrument.settings.articulations
            switch = (
                next((s for s in switches.keys if s.key == event.key), None)
                if switches is not None
                else None
            )
            if switch is not None:
                articulations = dict(state.articulations)
                articulations[event.part] = switch.articulation
                state = state.model_copy(update={'articulations': articulations})
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
            if any(s.key_conditions for s in instrument.slots):
                state = state.model_copy(
                    update={
                        'held_keys': state.held_keys
                        | {
                            event.part: state.held_keys.get(event.part, {})
                            | {event.trigger_id: event.key}
                        }
                    }
                )
            actions.append(
                TriggerContext(
                    tick=event.tick,
                    ordinal=event.ordinal,
                    part=event.part,
                    trigger_id=event.trigger_id,
                    velocity=event.velocity,
                    controls={
                        n: c.default for n, c in instrument.settings.controls.items()
                    }
                    | event.controls,
                )
            )
            if any(s.sequence is not None for s in instrument.slots):
                counts = state.note_on_counts | {
                    event.part: state.note_on_counts.get(event.part, 0) + 1
                }
                state = state.model_copy(update={'note_on_counts': counts})
            selected = (
                []
                if switch is not None and switch.consume
                else selected_slots(
                    event.part,
                    enums.TriggerKind.start,
                    event.key,
                    event.velocity,
                    event,
                )
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
            if any(s.previous_key is not None for s in instrument.slots):
                state = state.model_copy(
                    update={
                        'previous_keys': state.previous_keys | {event.part: event.key}
                    }
                )
    return SampleTrace(
        seed=seed,
        actions=actions,
        snapshots=[
            SampleSnapshot(
                tick=events[-1].tick if events else 0,
                ordinal=events[-1].ordinal if events else 0,
                selection=state,
                voices=voices,
                triggers=triggers,
            )
        ],
    )
