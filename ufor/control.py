"""Clock units, instance ownership, and ordered scalar-control events."""

from enum import StrEnum, auto
from fractions import Fraction
from math import ceil
from typing import Annotated, Self

from pydantic import BeforeValidator, Field, model_validator

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


class TempoPoint(Model):
    at_seconds: Rational = Field(ge=0)
    beat: Rational
    bpm: Rational = Field(gt=0)
    running: bool = True


class TransportSeekError(ValueError):
    """A queued musical target was invalidated by a host transport jump."""


class TempoMap(Model):
    """Host-resolved quarter-note positions, including stops and transport seeks."""

    points: list[TempoPoint] = Field(min_length=1)

    @model_validator(mode='after')
    def ordered_points(self) -> Self:
        if self.points[0].at_seconds != 0 or any(
            b.at_seconds <= a.at_seconds
            for a, b in zip(self.points, self.points[1:], strict=False)
        ):
            raise ValueError('tempo points must start at zero and increase in time')
        return self

    def beat_at(self, seconds: Fraction) -> Fraction:
        if seconds < 0:
            raise ValueError('clock time must be nonnegative')
        point = self.points[0]
        for candidate in self.points[1:]:
            if candidate.at_seconds > seconds:
                break
            point = candidate
        if not point.running:
            return point.beat
        return point.beat + (seconds - point.at_seconds) * point.bpm / 60

    def quantized_beat(self, seconds: Fraction, division: Fraction) -> Fraction:
        if division <= 0:
            raise ValueError('beat division must be positive')
        beat = self.beat_at(seconds)
        return ceil(beat / division) * division

    def time_for_beat(self, beat: Fraction, after: Fraction) -> Fraction | None:
        """Resolve a pending target beat, or cancel it at the first host seek."""
        self.beat_at(after)
        for index, point in enumerate(self.points):
            following = self.points[index + 1] if index + 1 < len(self.points) else None
            if following is not None and following.at_seconds <= after:
                continue
            start = max(after, point.at_seconds)
            current = (
                point.beat + (start - point.at_seconds) * point.bpm / 60
                if point.running
                else point.beat
            )
            if beat < current:
                raise ValueError('pending beat precedes the clock position')
            if point.running:
                reached = point.at_seconds + (beat - point.beat) * 60 / point.bpm
                if reached >= start and (
                    following is None or reached <= following.at_seconds
                ):
                    if following is None or reached < following.at_seconds:
                        return reached
            if following is None:
                return None
            boundary_beat = (
                point.beat + (following.at_seconds - point.at_seconds) * point.bpm / 60
                if point.running
                else point.beat
            )
            if following.beat != boundary_beat:
                raise TransportSeekError('pending beat cancelled by transport seek')
            if point.running and reached == following.at_seconds:
                return reached
        return None


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
