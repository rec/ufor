"""Finite pitches and repeating or finite ratios, independent of instruments."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, ConfigDict, Field, ValidationInfo
from reccy.configuration import units

from . import number
from .base import Model
from .expression import MAX_EXPRESSION_LENGTH, evaluate, evaluate_quantity, positive
from .number import PitchNumber

MAX_TABLE_ENTRIES = 10000


def frequency_expression(value: object, info: ValidationInfo) -> object:
    if isinstance(value, str):
        if len(value) > MAX_EXPRESSION_LENGTH:
            raise ValueError('Pitch expression exceeds 4096 characters')
        if info.context and info.context.get('portable'):
            result, has_unit = evaluate_quantity(value, 'hertz')
            return str(result) if has_unit else value
        if units.quantity_unit(value) is not None:
            return str(units.magnitude(value, 'hertz', exact=True))
    return value


def portable_integer(value: object, info: ValidationInfo) -> object:
    if info.context and info.context.get('portable'):
        if type(value) is not int:
            raise ValueError('Portable tuning integers must be JSON integers')
        number.bounded_integer(value)
    return value


def portable_boolean(value: object, info: ValidationInfo) -> object:
    if info.context and info.context.get('portable') and type(value) is not bool:
        raise ValueError('Portable tuning booleans must be JSON booleans')
    return value


def portable_detune(value: object, info: ValidationInfo) -> object:
    if info.context and info.context.get('portable'):
        if isinstance(value, str):
            return number.as_float(evaluate_quantity(value, 'musical_cent')[0])
        if isinstance(value, float):
            return float(value)
    return value


class Computed(Model):
    denominator_limit: Annotated[int, BeforeValidator(portable_integer)] = Field(
        0,
        ge=0,
        description='Maximum rational denominator; 0 disables approximation',
        json_schema_extra={'maximum': number.MAX_INTEGER},
    )
    notes_per_octave: Annotated[int, BeforeValidator(portable_integer)] = Field(
        12, gt=0, json_schema_extra={'maximum': number.MAX_INTEGER}
    )
    octave_ratio: Annotated[str, AfterValidator(positive)] = '2'

    def __call__(self, note_delta: int) -> PitchNumber:
        number.bounded_integer(note_delta)
        number.bounded_integer(self.notes_per_octave)
        ratio = number.checked_power(
            evaluate(self.octave_ratio),
            number.checked_fraction(note_delta, self.notes_per_octave),
        )
        return (
            number.positive_number(
                number.limit_denominator(ratio, self.denominator_limit)
            )
            if self.denominator_limit
            else number.positive_number(ratio)
        )

    def as_ratios(self) -> RatioTable:
        if self.notes_per_octave > MAX_TABLE_ENTRIES:
            raise ValueError('Table exceeds 10000 entries')
        return RatioTable(
            ratios=[str(self(i)) for i in range(self.notes_per_octave)],
            repeat_ratio=str(self(self.notes_per_octave)),
        )

    model_config = ConfigDict(revalidate_instances='always')


class RatioTable(Model):
    """Reference-relative ratios; optional repetition multiplies each cycle."""

    ratios: list[Annotated[str, AfterValidator(positive)]] = Field(
        min_length=1, max_length=MAX_TABLE_ENTRIES
    )
    repeat_ratio: Annotated[str, AfterValidator(positive)] | None = None
    name: str = ''
    description: str = ''

    def __call__(self, degree: int) -> PitchNumber:
        number.bounded_integer(degree)
        ratios = table_values(self.ratios)
        if self.repeat_ratio is None:
            if not 0 <= degree < len(self.ratios):
                raise ValueError('Degree is outside the finite ratio table')
            return ratios[degree]
        cycle, offset = divmod(degree, len(self.ratios))
        return number.positive_number(
            number.checked_multiply(
                number.checked_power(evaluate(self.repeat_ratio), cycle), ratios[offset]
            )
        )

    model_config = ConfigDict(revalidate_instances='always')


class IntervalPattern(Model):
    """Adjacent frequency ratios; degree zero is unison."""

    intervals: list[Annotated[str, AfterValidator(positive)]] = Field(
        min_length=1, max_length=MAX_TABLE_ENTRIES
    )
    repeat: Annotated[bool, BeforeValidator(portable_boolean)] = True

    @property
    def ratios(self) -> list[PitchNumber]:
        return table_values(self.intervals)

    def __call__(self, degree: int) -> PitchNumber:
        number.bounded_integer(degree)
        ratios = self.ratios
        if not self.repeat:
            if not 0 <= degree <= len(self.intervals):
                raise ValueError('Degree is outside the finite interval pattern')
            return number.positive_number(number.checked_product(ratios[:degree]))
        cycle, offset = divmod(degree, len(self.intervals))
        return number.positive_number(
            number.checked_multiply(
                number.checked_power(number.checked_product(ratios), cycle),
                number.checked_product(ratios[:offset]),
            )
        )

    model_config = ConfigDict(revalidate_instances='always')


class FrequencyTable(Model):
    """Absolute hertz values over a finite contiguous note range. Never wraps."""

    frequencies: list[
        Annotated[str, BeforeValidator(frequency_expression), AfterValidator(positive)]
    ] = Field(min_length=1, max_length=MAX_TABLE_ENTRIES)
    first_note: Annotated[int, BeforeValidator(portable_integer)] = Field(
        0,
        json_schema_extra={
            'minimum': number.MIN_INTEGER,
            'maximum': number.MAX_INTEGER,
        },
    )

    def __call__(self, note: int) -> PitchNumber:
        number.bounded_integer(note)
        number.bounded_integer(self.first_note)
        frequencies = table_values(self.frequencies)
        try:
            index = number.checked_difference(note, self.first_note)
        except ValueError as error:
            raise ValueError('Note is outside the finite frequency table') from error
        if not 0 <= index < len(self.frequencies):
            raise ValueError('Note is outside the finite frequency table')
        return frequencies[index]

    model_config = ConfigDict(revalidate_instances='always')


class Tuning(Model):
    source: Computed | RatioTable | IntervalPattern | FrequencyTable
    root_note: Annotated[int, BeforeValidator(portable_integer)] = Field(
        69,
        json_schema_extra={
            'minimum': number.MIN_INTEGER,
            'maximum': number.MAX_INTEGER,
        },
    )
    root_frequency: Annotated[
        str, BeforeValidator(frequency_expression), AfterValidator(positive)
    ] = '440'
    detune_cents: Annotated[
        float, units.unit_validator('musical_cent'), BeforeValidator(portable_detune)
    ] = 0

    def __call__(self, note: int) -> PitchNumber:
        number.bounded_integer(note)
        if isinstance(self.source, FrequencyTable):
            frequency = self.source(note)
        else:
            frequency = number.checked_multiply(
                evaluate(self.root_frequency),
                self.source(number.checked_difference(note, self.root_note)),
            )
        if self.detune_cents == 0:
            return number.positive_number(frequency)
        try:
            ratio = number.cents_to_ratio(self.detune_cents)
        except OverflowError as error:
            raise ValueError('Pitch arithmetic exceeds the 64-bit domain') from error
        return number.positive_number(number.checked_multiply(frequency, ratio))

    model_config = ConfigDict(revalidate_instances='always')


def table_values(values: list[str]) -> list[PitchNumber]:
    if not 1 <= len(values) <= MAX_TABLE_ENTRIES:
        raise ValueError('Table requires between 1 and 10000 entries')
    return [number.positive_number(evaluate(i)) for i in values]
