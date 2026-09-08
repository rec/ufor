"""Finite pitches and repeating or finite ratios, independent of instruments."""

from __future__ import annotations

from fractions import Fraction
from functools import cached_property
from math import prod
from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from .base import Model
from .expression import evaluate, positive
from .number import Number, cents


class Computed(Model):
    kind: Literal['computed'] = 'computed'
    limit: int = Field(
        0, ge=0, description='Maximum rational denominator; 0 disables approximation'
    )
    notes_per_octave: int = Field(12, gt=0)
    octave_ratio: Annotated[str, AfterValidator(positive)] = '2'

    def __call__(self, note_delta: int) -> Number:
        ratio = evaluate(self.octave_ratio) ** (note_delta / self.notes_per_octave)
        return Fraction(ratio).limit_denominator(self.limit) if self.limit else ratio

    def as_ratios(self) -> RatioTable:
        return RatioTable(
            values=[str(self(i)) for i in range(self.notes_per_octave)],
            repeat_ratio=str(self(self.notes_per_octave)),
        )


class RatioTable(Model):
    """Reference-relative ratios; optional repetition multiplies each cycle."""

    kind: Literal['ratios'] = 'ratios'
    values: list[Annotated[str, AfterValidator(positive)]] = Field(min_length=1)
    repeat_ratio: Annotated[str, AfterValidator(positive)] | None = None
    name: str = ''
    desc: str = ''

    @cached_property
    def ratios(self) -> list[Number]:
        return [evaluate(i) for i in self.values]

    def __call__(self, degree: int) -> Number:
        if self.repeat_ratio is None:
            if not 0 <= degree < len(self.values):
                raise ValueError('Degree is outside the finite ratio table')
            return self.ratios[degree]
        cycle, offset = divmod(degree, len(self.values))
        return evaluate(self.repeat_ratio) ** cycle * self.ratios[offset]


class IntervalPattern(Model):
    """Adjacent frequency ratios; degree zero is unison."""

    kind: Literal['intervals'] = 'intervals'
    intervals: list[Annotated[str, AfterValidator(positive)]] = Field(min_length=1)
    repeat: bool = True

    @cached_property
    def ratios(self) -> list[Number]:
        return [evaluate(i) for i in self.intervals]

    def __call__(self, degree: int) -> Number:
        if not self.repeat:
            if not 0 <= degree <= len(self.intervals):
                raise ValueError('Degree is outside the finite interval pattern')
            return prod(self.ratios[:degree])
        cycle, offset = divmod(degree, len(self.intervals))
        return prod(self.ratios) ** cycle * prod(self.ratios[:offset])


class FrequencyTable(Model):
    """Absolute hertz values over a finite contiguous note range. Never wraps."""

    kind: Literal['frequencies'] = 'frequencies'
    values: list[Annotated[str, AfterValidator(positive)]] = Field(min_length=1)
    first_note: int = 0

    @cached_property
    def frequencies(self) -> list[Number]:
        return [evaluate(i) for i in self.values]

    def __call__(self, note: int) -> Number:
        index = note - self.first_note
        if not 0 <= index < len(self.values):
            raise ValueError('Note is outside the finite frequency table')
        return self.frequencies[index]


class Tuning(Model):
    source: Annotated[
        Computed | RatioTable | IntervalPattern | FrequencyTable,
        Field(discriminator='kind'),
    ]
    root_note: int = 69
    root_frequency: Annotated[str, AfterValidator(positive)] = '440'
    detune: float = 0

    def __call__(self, note: int) -> Number:
        if isinstance(self.source, FrequencyTable):
            frequency = self.source(note)
        else:
            frequency = evaluate(self.root_frequency) * self.source(
                note - self.root_note
            )
        return frequency * cents(self.detune)
