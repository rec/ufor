"""Shared LFO reset declarations and stateless activation mathematics."""

from enum import StrEnum, auto
from fractions import Fraction


class Reset(StrEnum):
    free = auto()
    trigger = auto()
    transport = auto()


def activation_weight(age: Fraction, delay: Fraction, fade_in: Fraction) -> float:
    if age < delay:
        return 0.0
    return float(min(Fraction(1), (age - delay) / fade_in)) if fade_in else 1.0
