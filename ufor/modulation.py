"""Typed scalar routes for instrument and processor parameter contexts."""

from enum import StrEnum, auto
from itertools import pairwise
from math import exp, fsum, log
from typing import Annotated, Literal, Self, overload

import pydantic
from pydantic import Field, TypeAdapter, model_validator
from reccy.configuration import units

from . import modulation_contract
from .base import Model, UnitScalar, unique
from .control import Scope
from .modulation_contract import Identifier, Scalar, finite, records


class Unit(StrEnum):
    logical = auto()
    ratio = auto()
    db = auto()
    cents = auto()
    hz = auto()
    normalized = auto()
    volts = auto()
    seconds = auto()
    beats = auto()
    radians = auto()


def unit_number(value: float | str, unit: Unit) -> float:
    """Normalize a referenced parameter once its unit contract is known."""
    return TypeAdapter(
        Annotated[float, units.unit_validator(UNIT_NAMES[unit])]
    ).validate_python(value)


@overload
def unit_fields(
    value: dict[str, object],
    fields: list[str],
    info: pydantic.ValidationInfo | None = None,
) -> dict[str, object]: ...


@overload
def unit_fields(
    value: object, fields: list[str], info: pydantic.ValidationInfo | None = None
) -> object: ...


def unit_fields(
    value: object, fields: list[str], info: pydantic.ValidationInfo | None = None
) -> object:
    """Normalize numeric fields in the unit declared by their containing object."""
    if not isinstance(value, dict):
        return value
    declared = value.get('unit')
    unit = UNIT_NAMES.get(declared) if isinstance(declared, str) else None
    if unit is None:
        return value
    if info is not None and info.context and info.context.get('portable'):
        return dict(value) | {
            f: modulation_contract.scalar_quantity(value[f], str(declared))
            for f in fields
            if f in value
        }
    return dict(value) | {
        f: units.magnitude(value[f], unit)
        for f in fields
        if f in value and isinstance(value[f], str)
    }


class Operation(StrEnum):
    add = auto()
    multiply = auto()


class Interpolation(StrEnum):
    linear = auto()
    step = auto()
    exponential = auto()


class Target(Model):
    name: Identifier
    parameter: Identifier

    model_config = pydantic.ConfigDict(revalidate_instances='always')


class Parameter(Model):
    target: Target
    unit: Unit
    scope: Scope
    minimum: Annotated[UnitScalar, pydantic.BeforeValidator(modulation_contract.scalar)]
    maximum: Annotated[UnitScalar, pydantic.BeforeValidator(modulation_contract.scalar)]
    default: Annotated[UnitScalar, pydantic.BeforeValidator(modulation_contract.scalar)]

    @model_validator(mode='before')
    @classmethod
    def declared_units(cls, value: object, info: pydantic.ValidationInfo) -> object:
        return unit_fields(value, ['minimum', 'maximum', 'default'], info)

    @model_validator(mode='after')
    def domain(self) -> Self:
        if not self.minimum <= self.default <= self.maximum:
            raise ValueError('parameter default must be inside its ordered domain')
        if self.unit == Unit.hz and self.minimum <= 0:
            raise ValueError('Hz parameters require a positive domain')
        if self.unit in (Unit.seconds, Unit.beats) and self.minimum < 0:
            raise ValueError('duration parameters require a nonnegative domain')
        if self.unit == Unit.normalized and not -1 <= self.minimum <= self.maximum <= 1:
            raise ValueError('normalized parameters must remain within [-1, 1]')
        return self

    model_config = pydantic.ConfigDict(revalidate_instances='always')


class Source(Model):
    name: Identifier
    scope: Literal['instrument', 'part', 'trigger', 'voice']
    minimum: Scalar
    maximum: Scalar

    @model_validator(mode='after')
    def ordered_domain(self) -> Self:
        if self.maximum < self.minimum:
            raise ValueError('source maximum must not precede its minimum')
        return self

    model_config = pydantic.ConfigDict(revalidate_instances='always')


class Point(Model):
    input: Scalar
    amount: Annotated[UnitScalar, pydantic.BeforeValidator(modulation_contract.scalar)]

    model_config = pydantic.ConfigDict(revalidate_instances='always')


class Route(Model):
    name: Identifier
    source: Identifier
    target: Target
    operation: Operation
    unit: Unit
    points: list[Point] = Field(min_length=1, max_length=9999)
    interpolation: Interpolation = Interpolation.linear

    @model_validator(mode='before')
    @classmethod
    def declared_units(cls, value: object, info: pydantic.ValidationInfo) -> object:
        if not isinstance(value, dict) or not isinstance(value.get('points'), list):
            return value
        records(1 + len(value['points']))
        return dict(value) | {
            'points': [
                {
                    k: v
                    for k, v in unit_fields(
                        dict(p) | {'unit': value.get('unit')}, ['amount'], info
                    ).items()
                    if k != 'unit'
                }
                if isinstance(p, dict)
                else p
                for p in value['points']
            ]
        }

    @model_validator(mode='after')
    def ordered_points(self) -> Self:
        if any(b.input <= a.input for a, b in pairwise(self.points)):
            raise ValueError('mapping inputs must be strictly increasing')
        if self.interpolation == Interpolation.exponential and any(
            p.amount <= 0 for p in self.points
        ):
            raise ValueError('exponential mapping amounts must be positive')
        return self

    model_config = pydantic.ConfigDict(revalidate_instances='always')


class Modulation(Model):
    parameters: list[Parameter] = Field(default_factory=list, max_length=10000)
    sources: list[Source] = Field(default_factory=list, max_length=10000)
    routes: list[Route] = Field(default_factory=list, max_length=10000)

    @model_validator(mode='before')
    @classmethod
    def preparation_budget(cls, value: object) -> object:
        if isinstance(value, dict):
            arrays = [value.get(k, []) for k in ('parameters', 'sources', 'routes')]
            if all(isinstance(a, (list, tuple)) for a in arrays):
                count = sum(len(a) for a in arrays)
                records(count)
                for route in arrays[2]:
                    points = (
                        route.points
                        if isinstance(route, Route)
                        else route.get('points', [])
                        if isinstance(route, dict)
                        else []
                    )
                    if isinstance(points, (list, tuple)):
                        count += len(points)
                        records(count)
        return value

    @model_validator(mode='after')
    def references_and_units(self) -> Self:
        records(self.record_count())
        unique([s.name for s in self.sources], 'source IDs')
        unique([r.name for r in self.routes], 'route IDs')
        parameters = {p.target: p for p in self.parameters}
        if len(parameters) != len(self.parameters):
            raise ValueError('duplicate parameter targets')
        sources = {s.name: s for s in self.sources}
        for route in self.routes:
            if route.source not in sources or route.target not in parameters:
                raise ValueError(
                    f'route {route.name} references an unknown source or target'
                )
            source, parameter = sources[route.source], parameters[route.target]
            unit = parameter.unit if route.operation == Operation.add else Unit.ratio
            if route.unit != unit:
                raise ValueError(f'route {route.name} requires unit {unit}')
            if parameter.scope == Scope.instrument and source.scope != 'instrument':
                raise ValueError(
                    'instrument targets require an instrument-scoped source'
                )
            if any(
                not source.minimum <= p.input <= source.maximum for p in route.points
            ):
                raise ValueError(f'route {route.name} points exceed its source domain')
        return self

    def record_count(self) -> int:
        return (
            len(self.parameters)
            + len(self.sources)
            + sum(1 + len(r.points) for r in self.routes)
        )

    model_config = pydantic.ConfigDict(revalidate_instances='always')


class SourceValue(Model):
    value: Scalar
    weight: Scalar = Field(default=1, ge=0, le=1)

    model_config = pydantic.ConfigDict(revalidate_instances='always')


class ParameterValue(Model):
    target: Target
    value: Scalar

    model_config = pydantic.ConfigDict(revalidate_instances='always')


def map_value(route: Route, value: float) -> float:
    """Clamp outside the knots; a step changes at the knot, not after it."""
    finite(value)
    if value <= route.points[0].input:
        return route.points[0].amount
    for first, second in pairwise(route.points):
        if value < second.input:
            if route.interpolation == Interpolation.step:
                return first.amount
            progress = finite(
                finite(value - first.input) / finite(second.input - first.input)
            )
            if route.interpolation == Interpolation.exponential:
                return finite(
                    exp(
                        (1 - progress) * log(first.amount)
                        + progress * log(second.amount)
                    )
                )
            return finite(
                first.amount + finite(progress * finite(second.amount - first.amount))
            )
    return route.points[-1].amount


def evaluate(
    modulation: Modulation,
    values: dict[str, SourceValue],
    base_values: list[ParameterValue] | None = None,
) -> list[ParameterValue]:
    """Evaluate one resolved instance context without loading generators or devices."""
    records(modulation.record_count())
    records(len(values))
    records(len(base_values or []))
    sources = {s.name: s for s in modulation.sources}
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
    for route in sorted(modulation.routes, key=lambda r: (r.source, r.name)):
        if route.source not in values:
            raise ValueError(f'missing modulation source {route.source}')
        source_value = values[route.source]
        amount = map_value(route, source_value.value)
        neutral = 0 if route.operation == Operation.add else 1
        amount = finite(
            neutral + finite(source_value.weight * finite(amount - neutral))
        )
        contributions[route.target].append((route.operation, amount))
    result: list[ParameterValue] = []
    for target, parameter in parameters.items():
        base = overrides.get(target, parameter.default)
        if not parameter.minimum <= base <= parameter.maximum:
            raise ValueError(
                f'base value for {target.name}.{target.parameter} is outside its domain'
            )
        terms = contributions[target]
        try:
            added = finite(base + fsum(v for o, v in terms if o == Operation.add))
        except OverflowError as error:
            raise ValueError('Scalar sum exceeds the f64 range') from error
        product = 1.0
        for operation, amount in terms:
            if operation == Operation.multiply:
                product = finite(product * amount)
        value = finite(added * product)
        if not parameter.minimum <= value <= parameter.maximum:
            raise ValueError(
                f'modulated {target.name}.{target.parameter} is outside its domain'
            )
        result.append(ParameterValue(target=target, value=value))
    return result


UNIT_NAMES = {
    Unit.logical: 'dimensionless',
    Unit.ratio: 'dimensionless',
    Unit.db: 'decibel',
    Unit.cents: 'musical_cent',
    Unit.hz: 'hertz',
    Unit.normalized: 'dimensionless',
    Unit.volts: 'volt',
    Unit.seconds: 'second',
    Unit.beats: 'beat',
    Unit.radians: 'radian',
}
