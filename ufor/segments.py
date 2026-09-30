"""Shared authored segments for envelopes and timeline curves."""

import re
from enum import StrEnum, auto
from fractions import Fraction
from typing import Annotated

from pydantic import Field, StrictBool, field_serializer, model_validator
from pydantic.functional_validators import BeforeValidator

from . import control
from .base import FiniteScalar, Model


def duration(value: object) -> Fraction:
    if isinstance(value, (int, Fraction)) and not isinstance(value, bool):
        return Fraction(value)
    if not isinstance(value, str):
        raise ValueError('segment duration must use an explicit unit')
    match = re.fullmatch(r'([^ ]+) (ms|s|beat|beats|frame|frames)', value)
    if match is None:
        raise ValueError('segment duration must use an explicit unit')
    amount = control.rational(match.group(1))
    unit = match.group(2)
    if unit == 's':
        return amount
    if unit == 'ms':
        return amount / 1000
    if unit in {'beat', 'beats'}:
        return amount
    raise ValueError('segment frames require a declared timebase')


class DurationUnit(StrEnum):
    seconds = auto()
    beats = auto()


Duration = Annotated[Fraction, BeforeValidator(duration)]


class Segment(Model):
    duration: Duration = Field(ge=0)
    to: FiniteScalar | StrictBool
    curve: float = 0
    duration_unit: DurationUnit = Field(default=DurationUnit.seconds, exclude=True)

    @model_validator(mode='before')
    @classmethod
    def authored_unit(cls, value: object) -> object:
        if isinstance(value, dict) and isinstance(value.get('duration'), str):
            authored = value['duration']
            unit = (
                DurationUnit.beats
                if authored.endswith((' beat', ' beats'))
                else DurationUnit.seconds
            )
            if 'duration_unit' in value and value['duration_unit'] != unit:
                raise ValueError('segment duration unit conflicts with its suffix')
            return value | {'duration_unit': unit}
        return value

    @field_serializer('duration')
    def serialized_duration(self, value: Fraction) -> str:
        unit = 'beat' if self.duration_unit == DurationUnit.beats else 's'
        return f'{value} {unit}'
