"""Public composition interfaces and direct references, without file access."""

from enum import StrEnum, auto
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, StrictInt, field_validator, model_validator

from .base import Identifier, Model, unique
from .document import Document
from .modulation import Target
from .streams import AudioType
from .time import Timebase


class Definition(Model):
    path: str = Field(min_length=1)
    sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')

    @field_validator('path')
    @classmethod
    def relative_path(cls, value: str) -> str:
        if (
            PurePosixPath(value).is_absolute()
            or PureWindowsPath(value).drive
            or urlsplit(value).scheme
            or '\\' in value
            or str(PurePosixPath(value)) == '.'
        ):
            raise ValueError('definition path must be a relative POSIX document path')
        return value


class Address(Model):
    node: Identifier
    port: Identifier


class Node(Model):
    id: Identifier
    definition: Definition
    parameters: dict[Identifier, float] = Field(default_factory=dict)


class Connection(Model):
    source: Address
    destination: Address


class EventType(Model):
    family: Literal['event'] = 'event'
    timebase: Identifier
    kinds: list[
        Literal['midi', 'osc', 'key', 'trigger', 'release', 'control_change']
    ] = Field(min_length=1)

    @model_validator(mode='after')
    def distinct_kinds(self) -> Self:
        unique(self.kinds, 'event kind')
        return self


class Direction(StrEnum):
    input = auto()
    output = auto()


class NormalizeMode(StrEnum):
    none = auto()
    limit = auto()
    normalize = auto()


class StreamBinding(Model):
    stream: Identifier
    channels: list[StrictInt] | None = None

    @model_validator(mode='after')
    def ordered_channels(self) -> Self:
        if self.channels is not None and (
            not self.channels
            or self.channels[0] < 0
            or self.channels != list(range(self.channels[0], self.channels[-1] + 1))
        ):
            raise ValueError(
                'selected channels must be nonempty, consecutive and nonnegative'
            )
        return self


class SequenceBinding(Model):
    sequence: Literal[True] = True


class PerformanceBinding(Model):
    performance: Literal[True] = True


class AudioBinding(Model):
    audio: Literal[True] = True


class MixBinding(Model):
    track: Identifier | None = None
    bus: Identifier | None = None
    start: int | None = Field(default=None, ge=0, strict=True)
    end: int | None = Field(default=None, gt=0, strict=True)
    gain: float = 1.0
    normalize: NormalizeMode = NormalizeMode.none

    @model_validator(mode='after')
    def source_and_extent(self) -> Self:
        if (self.track is None) == (self.bus is None):
            raise ValueError('mix binding requires exactly one track or bus')
        if self.end is not None and self.end <= (self.start or 0):
            raise ValueError('output end must exceed start')
        return self


class Port(Model):
    id: Identifier
    direction: Direction
    stream: AudioType | EventType
    binding: (
        StreamBinding
        | SequenceBinding
        | PerformanceBinding
        | AudioBinding
        | MixBinding
        | Address
    )


class Parameter(Model):
    id: Identifier
    binding: Target
    minimum: float | None = None
    maximum: float | None = None
    default: float | None = None

    @model_validator(mode='after')
    def ordered_range(self) -> Self:
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError('parameter minimum exceeds maximum')
        return self


class InterfaceDocument(Document):
    timebases: list[Timebase] = Field(default_factory=list)
    ports: list[Port] = Field(default_factory=list)
    parameters: list[Parameter] = Field(default_factory=list)

    @model_validator(mode='after')
    def public_interface(self) -> Self:
        unique((t.id for t in self.timebases), 'timebase ID')
        unique((p.id for p in self.ports), 'port ID')
        unique((p.id for p in self.parameters), 'parameter ID')
        unique((p.binding for p in self.parameters), 'parameter binding')
        clocks = {t.id for t in self.timebases}
        if any(p.stream.timebase not in clocks for p in self.ports):
            raise ValueError('public port references an unknown timebase')
        return self
