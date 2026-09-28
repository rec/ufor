"""Shared authored segments for envelopes and timeline curves."""

import re
from fractions import Fraction
from typing import Annotated

from pydantic import Field, StrictBool
from pydantic.functional_serializers import PlainSerializer
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
        raise ValueError('segment beats require a musical clock')
    raise ValueError('segment frames require a declared timebase')


def duration_text(value: Fraction) -> str:
    return f'{value} s'


Duration = Annotated[
    Fraction,
    BeforeValidator(duration),
    PlainSerializer(duration_text, return_type=str),
]


class Segment(Model):
    duration: Duration = Field(ge=0)
    to: FiniteScalar | StrictBool
    curve: float = 0
