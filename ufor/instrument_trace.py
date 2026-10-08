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
    key: int | None
    pitch_hz: float | None = None
    motion_key: int = Field(
        default=0, strict=True, ge=0, lt=2**64, exclude_if=lambda v: v == 0
    )


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


class LFOObservation(TraceAction):
    kind: Literal['lfo'] = 'lfo'
    name: Identifier
    action: Literal['reset', 'rate', 'pause', 'resume', 'reverse', 'seek', 'shift']
    rate: float | None = Field(default=None, ge=0)
    position: float | None = Field(default=None, ge=0, le=1)
    offset: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode='after')
    def rate_payload(self) -> Self:
        if (self.action == 'rate') != (self.rate is not None):
            raise ValueError('only LFO rate changes require a rate')
        if (self.action == 'seek') != (self.position is not None):
            raise ValueError('only LFO seek changes require a position')
        if (self.action == 'shift') != (self.offset is not None):
            raise ValueError('only LFO shift changes require an offset')
        return self


class MotionObservation(TraceAction):
    kind: Literal['motion'] = 'motion'
    name: Identifier
    part: Identifier
    trigger_id: Identifier
    action: Literal['pause', 'resume', 'reverse', 'seek', 'shift']
    position: float | None = Field(default=None, ge=0, le=1)
    offset: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode='after')
    def seek_payload(self) -> Self:
        if (self.action == 'seek') != (self.position is not None):
            raise ValueError('only Motion seek observations require a position')
        if (self.action == 'shift') != (self.offset is not None):
            raise ValueError('only Motion shift observations require an offset')
        return self


class Diagnostic(TraceAction):
    kind: Literal['diagnostic'] = 'diagnostic'
    code: Identifier
    message: str


class ActiveVoice(Model):
    voice_id: Identifier
    part: Identifier
    trigger_id: Identifier | None
    template: Identifier
    key: int | None
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
