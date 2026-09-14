"""Portable semantic actions for prepared sample-instrument performances."""

from enum import StrEnum, auto
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ..base import Identifier, Model, unique
from ..modulation import ParameterValue
from .processing import ChannelRoute, SoundSettings
from .selection import SelectionState


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
