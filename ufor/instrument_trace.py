"""Shared semantic lifecycle state for prepared instrument performances."""

from enum import StrEnum, auto
from typing import Literal, Self

from pydantic import Field, model_validator

from .base import Bipolar, Identifier, Model, UnitInterval, unique
from .samples import enums


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


class TriggerContext(TraceAction):
    """Initialize one onset's controls before any of its voice starts."""

    kind: Literal['trigger_context'] = 'trigger_context'
    part: Identifier
    trigger_id: Identifier
    velocity: UnitInterval
    controls: dict[Identifier, Bipolar]


class VoiceStart(TraceAction):
    kind: Literal['voice_start'] = 'voice_start'
    voice_id: Identifier
    part: Identifier
    trigger_id: Identifier | None
    template: Identifier
    key: int
    pitch_hz: float | None = None


class VoiceRetirement(TraceAction):
    kind: Literal['voice_retirement'] = 'voice_retirement'
    voice_id: Identifier
    cause: RetirementCause
    action: Literal['release', 'stop', 'fade']
    fade_seconds: float | None = Field(default=None, strict=True, gt=0)

    @model_validator(mode='after')
    def fade_duration(self) -> Self:
        if (self.action == 'fade') != (self.fade_seconds is not None):
            raise ValueError('only fade retirement requires fade_seconds')
        return self


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


class ActiveVoice(Model):
    voice_id: Identifier
    part: Identifier
    trigger_id: Identifier | None
    template: Identifier
    key: int
    template_trigger: enums.TriggerKind = enums.TriggerKind.start
    choke_group: Identifier | None = None


class ActiveTrigger(Model):
    part: Identifier
    trigger_id: Identifier
    key: int
    velocity: float
    pitch_hz: float | None = None
    templates: list[Identifier] = Field(default_factory=list)
    physically_released: bool = False
    logical_released: bool = False


class LifecycleSnapshot(Model):
    tick: int = Field(strict=True)
    ordinal: int = Field(ge=0, strict=True)
    voices: list[ActiveVoice] = Field(default_factory=list)
    triggers: list[ActiveTrigger] = Field(default_factory=list)

    @model_validator(mode='after')
    def unique_voice_ids(self) -> Self:
        unique((v.voice_id for v in self.voices), 'active voice ID')
        return self
