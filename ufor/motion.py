"""Portable definitions for reusable control motions."""

from fractions import Fraction
from typing import Annotated, Literal

from pydantic import Field, field_validator

from . import control
from .base import FiniteScalar, Model
from .lfo import Reset
from .oscillator import Waveform
from .score import Score
from .segments import Segment


class Cycle(Model):
    kind: Literal['cycle'] = 'cycle'
    shape: Waveform = Waveform.sine
    rate: control.Rational = Field(ge=0)
    phase: control.Rational = Field(default=Fraction(0), ge=0, lt=1)
    duty_cycle: control.Rational = Field(default=Fraction(1, 2), ge=0, le=1)
    reset: Reset = Reset.trigger
    delay: control.Rational = Field(default=Fraction(0), ge=0)
    fade_in: control.Rational = Field(default=Fraction(0), ge=0)

    @field_validator('rate', mode='before')
    @classmethod
    def hertz_rate(cls, value: object) -> object:
        if isinstance(value, str) and value.endswith(' Hz'):
            return value.removesuffix(' Hz')
        return value


class Contour(Model):
    kind: Literal['contour'] = 'contour'
    initial: FiniteScalar = 0.0
    segments: list[Segment] = Field(min_length=1)
    release: list[Segment] = Field(default_factory=list)


class MotionScore(Score):
    kind: Literal['motion'] = 'motion'
    body: Annotated[Cycle | Contour, Field(discriminator='kind')]
