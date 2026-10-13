"""Segmented control envelopes and pure event/state reference calculations."""

from enum import StrEnum, auto
from fractions import Fraction
from math import exp, expm1
from typing import Self

from pydantic import Field, model_validator

from . import control
from .base import Model
from .segments import Segment


class Retrigger(StrEnum):
    reset = auto()
    current = auto()
    ignore = auto()


class Curve(Model):
    """An autonomous scalar envelope, including unbounded gains and repetition."""

    initial: float = 0
    segments: list[Segment] = Field(min_length=1)
    repeat: bool = False

    @model_validator(mode='after')
    def repeat_period(self) -> Self:
        if self.repeat and not sum(s.duration for s in self.segments):
            raise ValueError('repeating curve requires a positive period')
        return self


def curve_at(curve: Curve, at: Fraction) -> float:
    """Seconds from activation; hold the final value or repeat the whole curve."""
    control.elapsed(at, Fraction(0))
    if curve.repeat:
        at %= sum(s.duration for s in curve.segments)
    value = curve.initial
    for segment in curve.segments:
        if at < segment.duration:
            return value + (segment.to - value) * curve_progress(
                float(at / segment.duration), segment.curve
            )
        at -= segment.duration
        value = segment.to
    return value


def curve_progress(progress: float, curve: float) -> float:
    """Normalized exponential, stable for either sign and exact at endpoints."""
    if not 0 <= progress <= 1:
        raise ValueError('segment progress must be in [0, 1]')
    if progress in (0, 1) or curve == 0:
        return progress
    if curve > 0:
        return exp(curve * (progress - 1)) * expm1(-curve * progress) / expm1(-curve)
    return expm1(curve * progress) / expm1(curve)
