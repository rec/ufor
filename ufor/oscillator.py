"""Portable oscillator parameters. No audio buffer generation."""

from enum import StrEnum, auto
from fractions import Fraction
from math import pi, sin

from pydantic import Field, field_validator

from .base import Model


class Waveform(StrEnum):
    sine = auto()
    square = auto()
    triangle = auto()


class Shape(Model):
    waveform: Waveform = Waveform.triangle
    duty_cycle: Fraction = Field(default=Fraction(1, 2), ge=0, le=1)

    @field_validator('duty_cycle', mode='before')
    @classmethod
    def numeric_duty_cycle(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError('duty_cycle must be numeric')
        return str(value) if isinstance(value, float) else value


class Oscillator(Shape):
    key_scale_note: int = 64
    key_scale: float = 0

    def gain(self, note_number: int) -> float:
        return 10 ** (self.key_scale * (note_number - self.key_scale_note) / 12 / 20)


def shape_value(waveform: Waveform, phase: Fraction, duty_cycle: Fraction) -> float:
    """Single control observation using Tuney's documented shape equations."""
    if not 0 <= phase < 1 or not 0 <= duty_cycle <= 1:
        raise ValueError('shape requires phase in [0, 1) and duty in [0, 1]')
    if waveform == Waveform.sine:
        return sin(2 * pi * float(phase))
    if waveform == Waveform.square:
        return 1.0 if phase < duty_cycle else -1.0
    if phase < duty_cycle:
        return float(2 * phase / duty_cycle - 1)
    return float((1 + duty_cycle - 2 * phase) / (1 - duty_cycle))
