"""Portable scalar timeline automation, evaluated in one resolved scope."""

from enum import StrEnum, auto
from fractions import Fraction
from itertools import pairwise
from math import fsum, prod
from typing import Literal, Self

from pydantic import Field, StrictBool, model_validator

from .base import Identifier, Model, Number, unique
from .control import Scope
from .modulation import Operation, Target, Unit
from .score import Score
from .time import Timebase


class Quantity(StrEnum):
    gain = auto()
    frequency = auto()
    gate = auto()


class Interpolation(StrEnum):
    hold = auto()
    linear = auto()


class Knot(Model):
    tick: int = Field(strict=True)
    value: Number | StrictBool


class TimelineCurve(Model):
    name: Identifier
    unit: Unit
    interpolation: Interpolation = Interpolation.linear
    knots: list[Knot] = Field(min_length=1)
    operation: Operation | None = None

    @model_validator(mode='after')
    def ordered(self) -> Self:
        if any(a.tick >= b.tick for a, b in pairwise(self.knots)):
            raise ValueError('curve ticks must be strictly increasing')
        return self


class Automation(Model):
    """One parameter's base value and explicitly combined timeline writers."""

    target: Target
    scope: Scope
    quantity: Quantity
    unit: Unit
    default: Number | StrictBool
    curves: list[TimelineCurve] = Field(default_factory=list)

    @model_validator(mode='after')
    def contracts(self) -> Self:
        required = {
            Quantity.gain: Unit.ratio,
            Quantity.frequency: Unit.hz,
            Quantity.gate: Unit.logical,
        }[self.quantity]
        if self.unit != required:
            raise ValueError(f'{self.quantity} requires unit {required}')
        check_value(self.quantity, self.default)
        unique([c.name for c in self.curves], 'curve names')
        if sum(c.operation is None for c in self.curves) > 1:
            raise ValueError('competing direct writers require explicit operations')
        for curve in self.curves:
            expected = (
                Unit.ratio if curve.operation == Operation.multiply else self.unit
            )
            if curve.unit != expected:
                raise ValueError(f'curve {curve.name} requires unit {expected}')
            if self.quantity == Quantity.gate:
                if curve.operation is not None:
                    raise ValueError('gates do not support arithmetic combination')
                if curve.interpolation != Interpolation.hold:
                    raise ValueError('gates require hold interpolation')
            for knot in curve.knots:
                if curve.operation is None:
                    check_value(self.quantity, knot.value)
                elif isinstance(knot.value, bool):
                    raise ValueError('arithmetic contributions must be numeric')
        return self


class AutomationScore(Score):
    kind: Literal['automation'] = 'automation'
    timebase: Timebase
    body: Automation


def evaluate(
    score: AutomationScore, tick: int, override: float | bool | None = None
) -> float | bool:
    """Before a curve starts, use the base or the operation's neutral value."""
    if isinstance(tick, bool) or not isinstance(tick, int):
        raise ValueError('query tick must be an integer')
    body = score.body
    base = body.default if override is None else override
    check_value(body.quantity, base)
    additions: list[float] = []
    multipliers: list[float] = []
    for curve in sorted(body.curves, key=lambda c: c.name):
        if tick < curve.knots[0].tick:
            continue
        value = curve_value(curve, tick)
        if curve.operation is None:
            base = value
        elif curve.operation == Operation.add:
            additions.append(float(value))
        else:
            multipliers.append(float(value))
    if body.quantity == Quantity.gate:
        return base
    result = (float(base) + fsum(additions)) * prod(multipliers)
    check_value(body.quantity, result)
    return result


def curve_value(curve: TimelineCurve, tick: int) -> float | bool:
    """Read an active curve; callers handle its pre-start base value."""
    if tick < curve.knots[0].tick:
        raise ValueError('curve has not started')
    for first, second in pairwise(curve.knots):
        if tick < second.tick:
            if curve.interpolation == Interpolation.hold:
                return first.value
            progress = Fraction(tick - first.tick, second.tick - first.tick)
            return (1 - float(progress)) * first.value + float(progress) * second.value
    return curve.knots[-1].value


def check_value(quantity: Quantity, value: float | bool) -> None:
    if quantity == Quantity.gate:
        if not isinstance(value, bool):
            raise ValueError('gate values must be booleans')
        return
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError('gain and frequency values must be numbers')
    if not float('-inf') < value < float('inf'):
        raise ValueError('control values must be finite')
    if quantity == Quantity.gain and value < 0:
        raise ValueError('gain must be nonnegative')
    if quantity == Quantity.frequency and value <= 0:
        raise ValueError('frequency must be positive')
