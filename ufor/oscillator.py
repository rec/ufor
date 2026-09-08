"""Portable oscillator parameters. No audio buffer generation."""

from enum import StrEnum, auto

from pydantic import Field

from .base import Model


class Waveform(StrEnum):
    sine = auto()
    square = auto()
    triangle = auto()


class Oscillator(Model):
    waveform: Waveform = Waveform.triangle
    duty_cycle: float = Field(0.5, ge=0, le=1)
    key_scale_note: int = 64
    key_scale: float = 0

    def gain(self, note_number: int) -> float:
        return 10 ** (self.key_scale * (note_number - self.key_scale_note) / 12 / 20)
