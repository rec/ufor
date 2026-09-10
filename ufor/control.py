"""Clock units, instance ownership, and ordered scalar-control events."""

from enum import StrEnum, auto
from fractions import Fraction
from typing import Annotated

from pydantic import BeforeValidator, Field

from .base import Model


class Clock(StrEnum):
    seconds = auto()
    beats = auto()


class Scope(StrEnum):
    voice = auto()
    instrument = auto()
    part = auto()


class Polarity(StrEnum):
    unipolar = auto()
    bipolar = auto()


def rational(value: object) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (str, int, Fraction)):
        raise ValueError('use a rational string or integer, not a floating-point time')
    try:
        return Fraction(value)
    except ZeroDivisionError as error:
        raise ValueError('rational denominator must not be zero') from error


Rational = Annotated[Fraction, BeforeValidator(rational)]


class ControlEvent(Model):
    at: Rational
    ordinal: int = Field(ge=0, strict=True)


def check_order(at: Fraction, ordinal: int, event: ControlEvent) -> None:
    if event.at < at or (event.at == at and event.ordinal <= ordinal):
        raise ValueError('control events must increase in (at, ordinal) order')


def elapsed(at: Fraction, since: Fraction) -> Fraction:
    if at < since:
        raise ValueError('query precedes current state; replay events to seek')
    return at - since
