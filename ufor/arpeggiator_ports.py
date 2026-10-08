"""Portable scalar input and discrete output ports for live arpeggiators."""

from enum import StrEnum, auto
from typing import Self

from pydantic import Field, model_validator

from .base import Model
from .control import Rational


class ArpeggiatorInputPort(StrEnum):
    gate = auto()
    density = auto()
    transposition = auto()


class ArpeggiatorOutputPort(StrEnum):
    step = auto()
    hit = auto()
    rest = auto()


class ArpeggiatorControl(Model, frozen=True):
    port: ArpeggiatorInputPort
    value: Rational

    @model_validator(mode='after')
    def density_range(self) -> Self:
        if self.port == ArpeggiatorInputPort.transposition:
            if self.value.denominator != 1 or not -(2**63) <= self.value < 2**63:
                raise ValueError('transposition requires signed 64-bit whole semitones')
        elif self.value < 0:
            raise ValueError('gate and density must be nonnegative')
        if self.port == ArpeggiatorInputPort.density and self.value > 1:
            raise ValueError('density must be between zero and one')
        return self


class ArpeggiatorOutput(Model, frozen=True):
    at: Rational = Field(ge=0)
    port: ArpeggiatorOutputPort
    index: int = Field(ge=0, strict=True)
    revision: int = Field(ge=0, strict=True)


class ArpeggiatorPortBatch(Model, frozen=True):
    events: list[ArpeggiatorOutput] = Field(default_factory=list, max_length=4096)
    exhausted: bool = False
