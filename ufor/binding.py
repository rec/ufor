"""Portable contracts for realizing a score through a named host adapter."""

from enum import StrEnum, auto
from math import log10
from typing import Literal, Self

from pydantic import Field, model_validator

from .assets import Asset
from .base import Identifier, Model, unique
from .interface import ScoreVersion
from .modulation import Unit
from .score import Score


class Conversion(StrEnum):
    identity = auto()
    affine = auto()
    log_normalize = auto()
    gain_db = auto()
    piecewise = auto()
    enum_table = auto()


class RangePolicy(StrEnum):
    reject = auto()
    clamp = auto()


class StateOrder(StrEnum):
    opaque_then_canonical = auto()


class MappingPoint(Model):
    input: float
    output: float


class EnumValue(Model):
    input: Identifier
    output: str = Field(min_length=1)


class StreamContract(Model):
    name: Identifier
    direction: Literal['input', 'output']
    family: Literal['audio', 'event', 'control', 'light']
    channels: int | None = Field(default=None, ge=1, strict=True)
    rate: int | None = Field(default=None, ge=1, strict=True)

    @model_validator(mode='after')
    def audio_shape(self) -> Self:
        if self.family == 'audio' and (self.channels is None or self.rate is None):
            raise ValueError('audio stream contracts require channels and rate')
        if self.family != 'audio' and (
            self.channels is not None or self.rate is not None
        ):
            raise ValueError('only audio stream contracts declare channels and rate')
        return self


class ChannelMapping(Model):
    logical: Identifier
    native: Identifier
    direction: Literal['input', 'output']


class InputControl(Model):
    source: Identifier
    protocol: Identifier
    field: Identifier
    target: Identifier
    source_unit: Unit
    target_unit: Unit
    conversion: Conversion = Conversion.identity
    scope: Literal['global', 'performance', 'voice'] = 'global'
    reset: Literal['hold', 'default', 'zero'] = 'hold'


class OpaqueState(Model):
    asset: Asset
    order: StateOrder = StateOrder.opaque_then_canonical


class ParameterMapping(Model):
    parameter: Identifier
    native_id: str = Field(min_length=1)
    unit: Unit
    conversion: Conversion = Conversion.identity
    input_min: float
    input_max: float
    output_min: float
    output_max: float
    update_ticks: int = Field(default=1, ge=1, strict=True)
    out_of_range: RangePolicy = RangePolicy.reject
    points: list[MappingPoint] = Field(default_factory=list)
    values: list[EnumValue] = Field(default_factory=list)

    @model_validator(mode='after')
    def ranges(self) -> Self:
        if self.input_max <= self.input_min or self.output_max <= self.output_min:
            raise ValueError('mapping ranges must increase')
        if self.conversion == Conversion.log_normalize and self.input_min <= 0:
            raise ValueError('log normalization requires positive input values')
        if self.conversion == Conversion.gain_db and (
            self.unit != Unit.ratio or self.input_min < 0
        ):
            raise ValueError('gain dB conversion requires a nonnegative ratio')
        if self.conversion == Conversion.piecewise:
            if len(self.points) < 2 or self.values:
                raise ValueError('piecewise conversion requires at least two points')
            if any(
                b.input <= a.input
                for a, b in zip(self.points, self.points[1:], strict=False)
            ):
                raise ValueError('piecewise inputs must increase')
            if any(
                b.output < a.output
                for a, b in zip(self.points, self.points[1:], strict=False)
            ):
                raise ValueError('piecewise conversion must be monotone')
        elif self.conversion == Conversion.enum_table:
            if not self.values or self.points:
                raise ValueError('enum conversion requires one or more values')
            unique((v.input for v in self.values), 'enum input')
            unique((v.output for v in self.values), 'enum output')
        elif self.points or self.values:
            raise ValueError('only table conversions may declare points or values')
        return self


class Capability(Model):
    name: Identifier
    live: bool
    offline: bool
    deterministic: bool
    state_restore: bool
    latency_ticks: int = Field(ge=0, strict=True)


class Binding(Model):
    definition: ScoreVersion
    adapter: str = Field(min_length=1)
    implementation: str = Field(min_length=1)
    implementation_revision: str = Field(min_length=1)
    capabilities: list[Capability] = Field(min_length=1)
    parameters: list[ParameterMapping] = Field(default_factory=list)
    streams: list[StreamContract] = Field(default_factory=list)
    channels: list[ChannelMapping] = Field(default_factory=list)
    controls: list[InputControl] = Field(default_factory=list)
    opaque_state: OpaqueState | None = None

    @model_validator(mode='after')
    def distinct(self) -> Self:
        unique((c.name for c in self.capabilities), 'capability')
        unique((p.parameter for p in self.parameters), 'mapped parameter')
        unique((p.native_id for p in self.parameters), 'native parameter')
        unique((s.name for s in self.streams), 'stream')
        unique((c.logical for c in self.channels), 'logical channel')
        unique((c.native for c in self.channels), 'native channel')
        for channel in self.channels:
            if channel.logical not in {
                s.name for s in self.streams if s.direction == channel.direction
            }:
                raise ValueError('channel mapping references an unknown logical stream')
        return self


class BindingScore(Score):
    kind: Literal['binding'] = 'binding'
    body: Binding


def map_parameter(mapping: ParameterMapping, value: float) -> float | None:
    """Convert one canonical value, returning None only for ratio silence in dB."""
    if not mapping.input_min <= value <= mapping.input_max:
        if mapping.out_of_range == RangePolicy.reject:
            raise ValueError(f'{mapping.parameter}: value is outside the binding range')
        value = min(max(value, mapping.input_min), mapping.input_max)
    if mapping.conversion == Conversion.identity:
        result = value
    elif mapping.conversion == Conversion.affine:
        result = mapping.output_min + (value - mapping.input_min) * (
            mapping.output_max - mapping.output_min
        ) / (mapping.input_max - mapping.input_min)
    elif mapping.conversion == Conversion.log_normalize:
        result = mapping.output_min + log10(value / mapping.input_min) * (
            mapping.output_max - mapping.output_min
        ) / log10(mapping.input_max / mapping.input_min)
    elif mapping.conversion == Conversion.gain_db:
        if value == 0:
            return None
        result = 20 * log10(value)
    elif mapping.conversion == Conversion.piecewise:
        for first, second in zip(mapping.points, mapping.points[1:], strict=False):
            if value <= second.input:
                result = first.output + (value - first.input) * (
                    second.output - first.output
                ) / (second.input - first.input)
                break
        else:
            result = mapping.points[-1].output
    else:
        raise ValueError('enum-table mappings require map_enum_parameter')
    if not mapping.output_min <= result <= mapping.output_max:
        raise ValueError(f'{mapping.parameter}: mapped value is outside native range')
    return result


def map_enum_parameter(mapping: ParameterMapping, value: Identifier) -> str:
    """Map an authored discrete value through an explicit native table."""
    if mapping.conversion != Conversion.enum_table:
        raise ValueError('mapping is not an enum table')
    for item in mapping.values:
        if item.input == value:
            return item.output
    raise ValueError(f'{mapping.parameter}: value is outside the binding table')
