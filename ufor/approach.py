"""Captured-level exponential stages resolved into ordinary envelope segments."""

from fractions import Fraction
from math import log
from typing import Literal, Self

import pydantic
from pydantic import Field, model_validator

from . import envelfo_contract, modulation_contract, number
from .base import FiniteScalar, Seconds
from .segments import Segment


class ExponentialApproach(envelfo_contract.Definition):
    kind: Literal['exponential_approach'] = 'exponential_approach'
    asymptote: FiniteScalar
    time_constant: Seconds
    threshold: FiniteScalar
    transition_to: FiniteScalar
    transition_seconds: Seconds
    minimum_transition_distance: FiniteScalar = Field(default=0, ge=0)
    minimum_time_constant: Seconds = 0

    @model_validator(mode='before')
    @classmethod
    def portable_seconds(cls, value: object, info: pydantic.ValidationInfo) -> object:
        if info.context and info.context.get('portable') and isinstance(value, dict):
            return value | {
                f: modulation_contract.scalar_quantity(value[f], 'seconds')
                for f in (
                    'time_constant',
                    'transition_seconds',
                    'minimum_time_constant',
                )
                if f in value
            }
        return value

    @model_validator(mode='after')
    def reachable_threshold(self) -> Self:
        if self.threshold == self.asymptote:
            raise ValueError('exponential threshold must differ from its asymptote')
        return self

    def resolve(self, initial: float) -> list[Segment]:
        """Capture an entry level; quantize derived durations once to nanoseconds."""
        initial = modulation_contract.finite(initial)
        distance = modulation_contract.finite(self.threshold - self.asymptote)
        start = initial
        result: list[Segment] = []
        if (
            self.time_constant
            and modulation_contract.finite(
                modulation_contract.finite(initial - self.threshold) * distance
            )
            > 0
        ):
            curve = modulation_contract.finite(
                log(
                    modulation_contract.finite(
                        distance / modulation_contract.finite(initial - self.asymptote)
                    )
                )
            )
            seconds = modulation_contract.finite(
                -max(self.time_constant, self.minimum_time_constant) * curve
            )
            result.append(
                Segment(
                    duration=_duration(seconds),
                    to=self.threshold,
                    curve=curve,
                )
            )
            start = self.threshold
        remaining = abs(modulation_contract.finite(start - self.transition_to))
        seconds = (
            modulation_contract.finite(self.transition_seconds * remaining)
            / max(remaining, self.minimum_transition_distance)
            if remaining
            else 0
        )
        result.append(
            Segment(
                duration=_duration(seconds),
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


def _duration(seconds: float) -> Fraction:
    return number.checked_fraction(
        round(modulation_contract.finite(seconds * 1_000_000_000)), 1_000_000_000
    )
