"""Shared authored segments for envelopes and timeline curves."""

from enum import StrEnum, auto
from fractions import Fraction
from typing import Annotated

from pydantic import Field, StrictBool, field_serializer, model_validator
from pydantic.functional_validators import BeforeValidator
from reccy.configuration import units

from . import control
from .base import FiniteScalar, Model


def duration(value: object) -> Fraction:
    if isinstance(value, (int, Fraction)) and not isinstance(value, bool):
        return Fraction(value)
    if not isinstance(value, str):
        raise ValueError('segment duration must use an explicit unit')
    match = units.QUANTITY.fullmatch(value.strip())
    if match is None or not match.group(2):
        raise ValueError('segment duration must use an explicit unit')
    unit = match.group(2)
    if unit in {'frame', 'frames'}:
        raise ValueError('segment frames require a declared timebase')
    canonical = 'beat' if unit in {'beat', 'beats'} else 'second'
    return control.rational(units.magnitude(value, canonical, exact=True))


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
                if (match := units.QUANTITY.fullmatch(authored.strip())) is not None
                and match.group(2) in {'beat', 'beats'}
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
