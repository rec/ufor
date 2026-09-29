"""Protocol inputs for transport-neutral performance events."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .base import Bipolar, Identifier, Model, unique
from .interface import ScoreReference
from .score import Score


class MidiController(Model):
    number: Annotated[int, Field(strict=True, ge=0, le=127)]
    control: Identifier
    minimum: Bipolar = 0.0
    maximum: Bipolar = 1.0

    @model_validator(mode='after')
    def ordered_range(self) -> Self:
        if self.minimum >= self.maximum:
            raise ValueError('MIDI controller output range must increase')
        return self


class MidiPerformanceInput(Model):
    channels: list[Annotated[int, Field(strict=True, ge=1, le=16)]] = Field(
        min_length=1
    )
    part: Identifier
    repeated_key_release: Literal['oldest', 'newest']
    tuning: ScoreReference | None = None
    controllers: list[MidiController] = Field(default_factory=list)

    @model_validator(mode='after')
    def distinct_sources(self) -> Self:
        unique(self.channels, 'MIDI channel')
        unique((c.number for c in self.controllers), 'MIDI controller')
        return self


class PerformanceInputBinding(Model):
    instrument: ScoreReference
    midi: list[MidiPerformanceInput] = Field(min_length=1)

    @model_validator(mode='after')
    def distinct_channels(self) -> Self:
        unique((c for m in self.midi for c in m.channels), 'MIDI channel')
        return self


class PerformanceBindingScore(Score):
    kind: Literal['performance_binding'] = 'performance_binding'
    body: PerformanceInputBinding
