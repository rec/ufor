"""Portable semantic actions for prepared sample-instrument performances."""

from enum import StrEnum, auto
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ..base import Identifier, Model, unique
from ..events import ControlChange, PerformanceEvent, Release
from ..modulation import ParameterValue
from . import enums
from .instrument import SampleInstrument, effective_selection, effective_settings
from .processing import ChannelRoute, SoundSettings
from .selection import SelectionState, choose


class RetirementCause(StrEnum):
    physical_release = auto()
    logical_release = auto()
    choke = auto()
    same_key = auto()
    voice_limit = auto()
    transport_stop = auto()


class TraceAction(Model):
    tick: int = Field(strict=True)
    ordinal: int = Field(ge=0, strict=True)


class VoiceStart(TraceAction):
    kind: Literal['voice_start'] = 'voice_start'
    voice_id: Identifier
    part: Identifier
    trigger_id: Identifier
    slot: Identifier
    slice: Identifier
    start_frame: int
    alignment_frames: int
    channels: list[ChannelRoute]
    settings: SoundSettings
    parameters: list[ParameterValue] = Field(default_factory=list)


class VoiceRetirement(TraceAction):
    kind: Literal['voice_retirement'] = 'voice_retirement'
    voice_id: Identifier
    cause: RetirementCause
    action: Literal['release', 'stop']


class ControlObservation(TraceAction):
    kind: Literal['control'] = 'control'
    control: Identifier
    value: float
    scope: Literal['instrument', 'part', 'trigger']
    part: Identifier | None = None
    trigger_id: Identifier | None = None


class Diagnostic(TraceAction):
    kind: Literal['diagnostic'] = 'diagnostic'
    code: Identifier
    message: str


Action = Annotated[
    VoiceStart | VoiceRetirement | ControlObservation | Diagnostic,
    Field(discriminator='kind'),
]


class ActiveVoice(Model):
    voice_id: Identifier
    part: Identifier
    trigger_id: Identifier
    slot: Identifier
    choke_group: Identifier | None = None


class TraceSnapshot(Model):
    tick: int = Field(strict=True)
    ordinal: int = Field(ge=0, strict=True)
    selection: SelectionState
    voices: list[ActiveVoice] = Field(default_factory=list)

    @model_validator(mode='after')
    def unique_voice_ids(self) -> Self:
        unique((v.voice_id for v in self.voices), 'active voice ID')
        return self


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
    groups = {g.name: g for g in instrument.groups}
    slices = {s.name: s for s in instrument.slices}
    selections = {s.name: s for s in instrument.instrument.selections}
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
        elif isinstance(event, Release):
            matched = [
                v
                for v in voices
                if v.part == event.part and v.trigger_id == event.trigger_id
            ]
            if not matched:
                actions.append(
                    Diagnostic(
                        tick=event.tick,
                        ordinal=event.ordinal,
                        code='unknown-release',
                        message=f'No active trigger {event.trigger_id}',
                    )
                )
            for voice in matched:
                actions.append(
                    VoiceRetirement(
                        tick=event.tick,
                        ordinal=event.ordinal,
                        voice_id=voice.voice_id,
                        cause=RetirementCause.physical_release,
                        action='release',
                    )
                )
                voices.remove(voice)
        else:
            instrument.validate_event(event)
            eligible = [
                s
                for s in instrument.slots
                if s.trigger.value == 'start'
                and s.mapping.lowest_key <= event.key <= s.mapping.highest_key
                and s.mapping.minimum_velocity
                <= event.velocity
                <= s.mapping.maximum_velocity
            ]
            selected = [
                s
                for s in eligible
                if effective_selection(s, groups.get(s.group)) is None
            ]
            for name, selection in selections.items():
                candidates = [
                    s
                    for s in eligible
                    if effective_selection(s, groups.get(s.group)) == name
                ]
                if candidates:
                    choice, state = choose(
                        selection,
                        state,
                        event.part,
                        enums.TriggerKind.start,
                        event.key,
                        sorted({s.take or s.name for s in candidates}),
                    )
                    selected.extend(
                        s for s in candidates if (s.take or s.name) == choice
                    )
            for slot in selected:
                for voice in list(voices):
                    if voice.choke_group in {c.group for c in slot.chokes}:
                        actions.append(
                            VoiceRetirement(
                                tick=event.tick,
                                ordinal=event.ordinal,
                                voice_id=voice.voice_id,
                                cause=RetirementCause.choke,
                                action='stop',
                            )
                        )
                        voices.remove(voice)
                voice_id = f'voice-{event.part}-{event.trigger_id}-{slot.name}'
                sample_slice = slices[slot.slice]
                actions.append(
                    VoiceStart(
                        tick=event.tick,
                        ordinal=event.ordinal,
                        voice_id=voice_id,
                        part=event.part,
                        trigger_id=event.trigger_id,
                        slot=slot.name,
                        slice=slot.slice,
                        start_frame=sample_slice.start_frame + slot.alignment_frames,
                        alignment_frames=slot.alignment_frames,
                        channels=slot.channels,
                        settings=effective_settings(slot, groups.get(slot.group)),
                    )
                )
                voices.append(
                    ActiveVoice(
                        voice_id=voice_id,
                        part=event.part,
                        trigger_id=event.trigger_id,
                        slot=slot.name,
                        choke_group=slot.choke_group,
                    )
                )
    return SemanticTrace(
        seed=seed,
        actions=actions,
        snapshots=[
            TraceSnapshot(
                tick=events[-1].tick if events else 0,
                ordinal=events[-1].ordinal if events else 0,
                selection=state,
                voices=voices,
            )
        ],
    )
