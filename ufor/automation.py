"""Portable scalar timeline automation, evaluated in one resolved scope."""

from enum import StrEnum, auto
from fractions import Fraction
from math import fsum, prod
from typing import Literal, Self

from pydantic import Field, StrictBool, model_validator

from .base import FiniteScalar, Identifier, Model, unique
from .control import Scope
from .interface import ControlBinding, ControlType, InterfaceScore, Output
from .modulation import Operation, Target, Unit
from .time import Timebase


class Quantity(StrEnum):
    gain = auto()
    frequency = auto()
    gate = auto()


class Interpolation(StrEnum):
    hold = auto()
    linear = auto()
    equal_power = auto()


class ArrangementGainTarget(Model):
    """A gain owned directly by the containing arrangement."""

    kind: Literal['clip', 'bus', 'route']
    name: Identifier
    destination: Identifier | None = None

    @model_validator(mode='after')
    def destination_matches_kind(self) -> Self:
        if (self.kind == 'route') != (self.destination is not None):
            raise ValueError('only route targets require destination')
        return self


class TimelineSegment(Model):
    duration: int = Field(ge=0, strict=True)
    to: FiniteScalar | StrictBool


class TimelineCurve(Model):
    name: Identifier
    unit: Unit
    interpolation: Interpolation = Interpolation.linear
    at: int = Field(strict=True)
    initial: FiniteScalar | StrictBool
    segments: list[TimelineSegment] = Field(default_factory=list)
    operation: Operation | None = None


class Automation(Model):
    """One parameter's base value and explicitly combined timeline writers."""

    target: Target | ArrangementGainTarget
    scope: Scope
    quantity: Quantity
    unit: Unit
    default: FiniteScalar | StrictBool
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
        if (
            isinstance(self.target, ArrangementGainTarget)
            and self.quantity != Quantity.gain
        ):
            raise ValueError('arrangement targets support gain only')
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
            if curve.interpolation == Interpolation.equal_power and (
                self.quantity != Quantity.gain or curve.operation is not None
            ):
                raise ValueError(
                    'equal-power interpolation requires a direct gain curve'
                )
            for value in [curve.initial, *(segment.to for segment in curve.segments)]:
                if curve.operation is None:
                    check_value(self.quantity, value)
                elif isinstance(value, bool):
                    raise ValueError('arithmetic contributions must be numeric')
        return self


class AutomationScore(InterfaceScore):
    kind: Literal['automation'] = 'automation'
    timebases: list[Timebase] = Field(min_length=1, max_length=1)
    outputs: list[Output] = Field(min_length=1, max_length=1)
    body: Automation

    @model_validator(mode='after')
    def control_export(self) -> Self:
        if self.inputs:
            raise ValueError('automation scores have no inputs')
        if self.parameters:
            raise ValueError('automation scores have no configurable parameters')
        output = self.outputs[0]
        if not isinstance(output.binding, ControlBinding) or not isinstance(
            output.stream, ControlType
        ):
            raise ValueError('automation scores export one control stream')
        timebase = self.timebases[0]
        if (
            output.stream.timebase != timebase.name
            or output.stream.quantity != self.body.quantity
            or output.stream.unit != self.body.unit
            or output.stream.scope != self.body.scope
        ):
            raise ValueError('automation output must match its curve contract')
        return self


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
        if tick < curve.at:
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
    if tick < curve.at:
        raise ValueError('curve has not started')
    value = curve.initial
    elapsed = Fraction(tick - curve.at)
    for segment in curve.segments:
        if elapsed < segment.duration:
            if curve.interpolation == Interpolation.hold:
                return value
            progress = elapsed / segment.duration
            if curve.interpolation == Interpolation.equal_power:
                return (
                    (1 - float(progress)) * float(value) ** 2
                    + float(progress) * float(segment.to) ** 2
                ) ** 0.5
            return (1 - float(progress)) * float(value) + float(progress) * float(
                segment.to
            )
        elapsed -= segment.duration
        value = segment.to
    return value


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
