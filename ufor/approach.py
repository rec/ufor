"""Captured-level exponential stages resolved into ordinary envelope segments."""

from fractions import Fraction
from math import log
from typing import Literal, Self

from pydantic import Field, model_validator

from .base import FiniteScalar, Model, Seconds
from .segments import Segment


class ExponentialApproach(Model):
    kind: Literal['exponential_approach'] = 'exponential_approach'
    asymptote: FiniteScalar
    time_constant: Seconds
    threshold: FiniteScalar
    transition_to: FiniteScalar
    transition_seconds: Seconds
    minimum_transition_distance: FiniteScalar = Field(default=0, ge=0)
    minimum_time_constant: Seconds = 0

    @model_validator(mode='after')
    def reachable_threshold(self) -> Self:
        if self.threshold == self.asymptote:
            raise ValueError('exponential threshold must differ from its asymptote')
        return self

    def resolve(self, initial: float) -> list[Segment]:
        """Capture an entry level; quantize derived durations once to nanoseconds."""
        distance = self.threshold - self.asymptote
        start = initial
        result: list[Segment] = []
        if self.time_constant and (initial - self.threshold) * distance > 0:
            curve = log(distance / (initial - self.asymptote))
            seconds = -max(self.time_constant, self.minimum_time_constant) * curve
            result.append(
                Segment(
                    duration=Fraction(round(seconds * 1_000_000_000), 1_000_000_000),
                    to=self.threshold,
                    curve=curve,
                )
            )
            start = self.threshold
        remaining = abs(start - self.transition_to)
        seconds = (
            self.transition_seconds
            * remaining
            / max(remaining, self.minimum_transition_distance)
            if remaining
            else 0
        )
        result.append(
            Segment(
                duration=Fraction(round(seconds * 1_000_000_000), 1_000_000_000),
                to=self.transition_to,
            )
        )
        return result


def resolve_segments(
    parts: list[Segment | ExponentialApproach], initial: float
) -> list[Segment]:
    """Resolve a captured phase once, preserving each authored stage's endpoint."""
    result: list[Segment] = []
    for part in parts:
        if isinstance(part, ExponentialApproach):
            result.extend(part.resolve(initial))
            initial = part.transition_to
        else:
            result.append(part)
            initial = float(part.to)
    return result
