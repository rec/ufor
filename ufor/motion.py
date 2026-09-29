"""Portable definitions for reusable control motions."""

from fractions import Fraction
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from . import control
from .base import FiniteScalar, Model
from .envelope import Retrigger
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
    polarity: control.Polarity = control.Polarity.unipolar
    hold: bool = True
    retrigger: Retrigger = Retrigger.current

    @model_validator(mode='after')
    def levels_match_polarity(self) -> Self:
        levels = [self.initial, *(s.to for s in [*self.segments, *self.release])]
        if any(not -1 <= value <= 1 for value in levels):
            raise ValueError('contour levels must be in [-1, 1]')
        if self.polarity == control.Polarity.unipolar and min(levels) < 0:
            raise ValueError('unipolar contour levels must be in [0, 1]')
        return self


class MotionUse(Model):
    scope: control.Scope = control.Scope.voice
    clock: control.Clock = control.Clock.seconds
    body: Annotated[Cycle | Contour, Field(discriminator='kind')]


class MotionScore(Score):
    kind: Literal['motion'] = 'motion'
    body: Annotated[Cycle | Contour, Field(discriminator='kind')]
