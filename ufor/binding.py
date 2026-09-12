"""Portable contracts for realizing a score through a named host adapter."""

from enum import StrEnum, auto
from math import log10
from typing import Literal, Self

from pydantic import Field, model_validator

from .base import Identifier, Model, unique
from .interface import ScoreVersion
from .modulation import Unit
from .score import Score


class Conversion(StrEnum):
    identity = auto()
    affine = auto()
    log_normalize = auto()
    gain_db = auto()


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

    @model_validator(mode='after')
    def distinct(self) -> Self:
        unique((c.name for c in self.capabilities), 'capability')
        unique((p.parameter for p in self.parameters), 'mapped parameter')
        unique((p.native_id for p in self.parameters), 'native parameter')
        return self


class BindingScore(Score):
    kind: Literal['binding'] = 'binding'
    body: Binding


def map_parameter(mapping: ParameterMapping, value: float) -> float | None:
    """Convert one canonical value, returning None only for ratio silence in dB."""
    if not mapping.input_min <= value <= mapping.input_max:
        raise ValueError(f'{mapping.parameter}: value is outside the binding range')
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
    else:
        if value == 0:
            return None
        result = 20 * log10(value)
    if not mapping.output_min <= result <= mapping.output_max:
        raise ValueError(f'{mapping.parameter}: mapped value is outside native range')
    return result
