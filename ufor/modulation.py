"""Typed scalar routes for instrument and processor parameter contexts."""

from enum import StrEnum, auto
from itertools import pairwise
from math import fsum, prod
from typing import Literal, Self

from pydantic import Field, model_validator

from .base import Identifier, Model, unique
from .control import Scope


class Unit(StrEnum):
    ratio = auto()
    db = auto()
    cents = auto()
    hz = auto()
    normalized = auto()
    volts = auto()
    seconds = auto()


class Operation(StrEnum):
    add = auto()
    multiply = auto()


class Interpolation(StrEnum):
    linear = auto()
    step = auto()


class Target(Model):
    node: Identifier
    parameter: Identifier


class Parameter(Model):
    target: Target
    unit: Unit
    scope: Scope
    minimum: float
    maximum: float
    default: float

    @model_validator(mode='after')
    def domain(self) -> Self:
        if not self.minimum <= self.default <= self.maximum:
            raise ValueError('parameter default must be inside its ordered domain')
        if self.unit == Unit.hz and self.minimum <= 0:
            raise ValueError('Hz parameters require a positive domain')
        if self.unit == Unit.seconds and self.minimum < 0:
            raise ValueError('duration parameters require a nonnegative domain')
        if self.unit == Unit.normalized and not -1 <= self.minimum <= self.maximum <= 1:
            raise ValueError('normalized parameters must remain within [-1, 1]')
        return self


class Source(Model):
    id: Identifier
    scope: Literal['instrument', 'part', 'trigger', 'voice']
    minimum: float
    maximum: float

    @model_validator(mode='after')
    def ordered_domain(self) -> Self:
        if self.maximum < self.minimum:
            raise ValueError('source maximum must not precede its minimum')
        return self


class Point(Model):
    input: float
    amount: float


class Route(Model):
    id: Identifier
    source: Identifier
    target: Target
    operation: Operation
    unit: Unit
    points: list[Point] = Field(min_length=1)
    interpolation: Interpolation = Interpolation.linear

    @model_validator(mode='after')
    def ordered_points(self) -> Self:
        if any(b.input <= a.input for a, b in pairwise(self.points)):
            raise ValueError('mapping inputs must be strictly increasing')
        return self


class Modulation(Model):
    parameters: list[Parameter] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)

    @model_validator(mode='after')
    def references_and_units(self) -> Self:
        unique([s.id for s in self.sources], 'source IDs')
        unique([r.id for r in self.routes], 'route IDs')
        parameters = {p.target: p for p in self.parameters}
        if len(parameters) != len(self.parameters):
            raise ValueError('duplicate parameter targets')
        sources = {s.id: s for s in self.sources}
        for route in self.routes:
            if route.source not in sources or route.target not in parameters:
                raise ValueError(
                    f'route {route.id} references an unknown source or target'
                )
            source, parameter = sources[route.source], parameters[route.target]
            unit = parameter.unit if route.operation == Operation.add else Unit.ratio
            if route.unit != unit:
                raise ValueError(f'route {route.id} requires unit {unit}')
            if parameter.scope == Scope.instrument and source.scope != 'instrument':
                raise ValueError(
                    'instrument targets require an instrument-scoped source'
                )
            if any(
                not source.minimum <= p.input <= source.maximum for p in route.points
            ):
                raise ValueError(f'route {route.id} points exceed its source domain')
        return self


class SourceValue(Model):
    value: float
    weight: float = Field(default=1, ge=0, le=1)


class ParameterValue(Model):
    target: Target
    value: float


def map_value(route: Route, value: float) -> float:
    """Clamp outside the knots; a step changes at the knot, not after it."""
    if value <= route.points[0].input:
        return route.points[0].amount
    for first, second in pairwise(route.points):
        if value < second.input:
            if route.interpolation == Interpolation.step:
                return first.amount
            progress = (value - first.input) / (second.input - first.input)
            return first.amount + progress * (second.amount - first.amount)
    return route.points[-1].amount


def evaluate(
    modulation: Modulation,
    values: dict[str, SourceValue],
    base_values: list[ParameterValue] | None = None,
) -> list[ParameterValue]:
    """Evaluate one resolved instance context without loading generators or devices."""
    sources = {s.id: s for s in modulation.sources}
    for name, value in values.items():
        if name not in sources:
            raise ValueError(f'unknown modulation source {name}')
        source = sources[name]
        if not source.minimum <= value.value <= source.maximum:
            raise ValueError(f'source {name} value is outside its domain')
    parameters = {p.target: p for p in modulation.parameters}
    overrides = {v.target: v.value for v in base_values or []}
    if len(overrides) != len(base_values or []):
        raise ValueError('multiple base values for a parameter')
    if overrides.keys() - parameters.keys():
        raise ValueError('base value references an unknown parameter')
    contributions: dict[Target, list[tuple[Operation, float]]] = {
        p: [] for p in parameters
    }
    for route in sorted(modulation.routes, key=lambda r: (r.source, r.id)):
        if route.source not in values:
            raise ValueError(f'missing modulation source {route.source}')
        source_value = values[route.source]
        amount = map_value(route, source_value.value)
        neutral = 0 if route.operation == Operation.add else 1
        amount = neutral + source_value.weight * (amount - neutral)
        contributions[route.target].append((route.operation, amount))
    result: list[ParameterValue] = []
    for target, parameter in parameters.items():
        base = overrides.get(target, parameter.default)
        if not parameter.minimum <= base <= parameter.maximum:
            raise ValueError(
                f'base value for {target.node}.{target.parameter} is outside its domain'
            )
        terms = contributions[target]
        value = (base + fsum(v for o, v in terms if o == Operation.add)) * prod(
            v for o, v in terms if o == Operation.multiply
        )
        if not parameter.minimum <= value <= parameter.maximum:
            raise ValueError(
                f'modulated {target.node}.{target.parameter} is outside its domain'
            )
        result.append(ParameterValue(target=target, value=value))
    return result
