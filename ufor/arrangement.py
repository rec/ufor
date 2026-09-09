from enum import StrEnum, auto
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from .base import Identifier, Model, unique
from .document import Document
from .encoding import Format
from .references import ParameterTarget, RecordSelector
from .streams import AudioType, FileDestination
from .time import Timebase


class Interpolation(StrEnum):
    hold = auto()
    linear = auto()
    equal_power = auto()


class NormalizeMode(StrEnum):
    none = auto()
    limit = auto()
    normalize = auto()


class SourceSpec(Model):
    id: Identifier
    record: Path | None = None
    selector: RecordSelector | None = None
    file: Path | None = None
    memory: str | None = None
    channels: list[int] = Field(default_factory=list)
    input_format: Format | None = None

    @model_validator(mode='after')
    def validate_location(self) -> Self:
        locations = [
            self.record is not None,
            self.file is not None,
            self.memory is not None,
        ]
        if sum(locations) != 1:
            raise ValueError('source requires exactly one of record, file, or memory')
        if self.record is not None:
            if self.selector is None:
                raise ValueError('record source requires selector')
            if self.channels:
                raise ValueError(
                    'channels are only allowed for file and memory sources'
                )
        else:
            if self.selector is not None:
                raise ValueError('selector is only allowed for record sources')
            if self.input_format is not None:
                raise ValueError('input_format is only allowed for record sources')
            if not self.channels:
                raise ValueError('file and memory sources require channels')
            if (
                self.channels
                != list(range(self.channels[0], self.channels[0] + len(self.channels)))
                or self.channels[0] < 0
            ):
                raise ValueError(
                    'file source channels must be consecutive and nonnegative'
                )
        return self


class TrackSpec(Model):
    id: Identifier
    stream: AudioType


class BusSpec(Model):
    id: Identifier
    stream: AudioType
    gain: float = 1.0


class ClipSpec(Model):
    id: Identifier
    source: Identifier
    track: Identifier
    source_start: int = Field(ge=0, strict=True)
    source_end: int = Field(gt=0, strict=True)
    timeline_start: int = Field(ge=0, strict=True)
    gain: float = 1.0

    @model_validator(mode='after')
    def validate_interval(self) -> Self:
        if self.source_end <= self.source_start:
            raise ValueError('source_end must be greater than source_start')
        return self


class RouteSpec(Model):
    source: Identifier
    destination: Identifier
    gain: float = 1.0


class AutomationPoint(Model):
    frame: int = Field(ge=0, strict=True)
    value: float


class AutomationSpec(Model):
    target: ParameterTarget
    interpolation: Interpolation = Interpolation.linear
    points: list[AutomationPoint] = Field(min_length=1)

    @model_validator(mode='after')
    def validate_points(self) -> Self:
        frames = [p.frame for p in self.points]
        if any(a >= b for a, b in zip(frames, frames[1:], strict=False)):
            raise ValueError('automation point frames must be strictly increasing')
        if self.interpolation == Interpolation.equal_power and any(
            p.value < 0 for p in self.points
        ):
            raise ValueError('equal-power automation values cannot be negative')
        return self


class OutputSpec(Model):
    id: Identifier
    source: Identifier
    start: int | None = Field(default=None, ge=0, strict=True)
    end: int | None = Field(default=None, gt=0, strict=True)
    normalize: NormalizeMode = NormalizeMode.none
    gain: float = 1.0

    @model_validator(mode='after')
    def validate_interval(self) -> Self:
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError('output end must be greater than start')
        return self


class Arrangement(Model):
    timebase: Identifier
    media_types: list[str] = Field(default_factory=lambda: ['audio'])
    sources: list[SourceSpec] = Field(default_factory=list)
    tracks: list[TrackSpec] = Field(default_factory=list)
    buses: list[BusSpec] = Field(default_factory=list)
    clips: list[ClipSpec] = Field(default_factory=list)
    routes: list[RouteSpec] = Field(default_factory=list)
    automation: list[AutomationSpec] = Field(default_factory=list)
    outputs: list[OutputSpec] = Field(default_factory=list)

    @model_validator(mode='after')
    def graph_references(self) -> Self:
        for kind, items in (
            ('source', self.sources),
            ('track', self.tracks),
            ('bus', self.buses),
            ('clip', self.clips),
            ('output', self.outputs),
        ):
            unique((i.id for i in items), f'{kind} ID')
        unique((a.target for a in self.automation), 'automation target')
        unique(((r.source, r.destination) for r in self.routes), 'route')
        tracks = {t.id: t.stream for t in self.tracks}
        buses = {b.id: b.stream for b in self.buses}
        if overlap := tracks.keys() & buses.keys():
            raise ValueError(f'Track and bus IDs collide: {sorted(overlap)}')
        streams = tracks | buses
        sources = {s.id for s in self.sources}
        clips = {c.id for c in self.clips}
        routes = {(r.source, r.destination) for r in self.routes}
        for clip in self.clips:
            if clip.source not in sources:
                raise ValueError(f'Clip {clip.id}: unknown source {clip.source}')
            if clip.track not in tracks:
                raise ValueError(f'Clip {clip.id}: unknown track {clip.track}')
        for route in self.routes:
            if route.source not in streams:
                raise ValueError(f'Route has unknown source {route.source}')
            if route.destination not in buses:
                raise ValueError(
                    f'Route has unknown destination bus {route.destination}'
                )
            if streams[route.source] != buses[route.destination]:
                raise ValueError('Route channel layouts and timebases must match')
        _ = self.bus_order
        for automation in self.automation:
            target = automation.target
            valid = (
                target.node in clips
                if target.kind == 'clip'
                else target.node in buses
                if target.kind == 'bus'
                else (target.node, target.destination) in routes
            )
            if not valid:
                raise ValueError(f'Unknown automation target {target!r}')
        for output in self.outputs:
            if output.source not in streams:
                raise ValueError(f'Output {output.id}: unknown source {output.source}')
        return self

    @property
    def bus_order(self) -> list[str]:
        buses = {b.id for b in self.buses}
        dependencies = {
            b.id: [
                r.source
                for r in self.routes
                if r.destination == b.id and r.source in buses
            ]
            for b in self.buses
        }
        try:
            return list(TopologicalSorter(dependencies).static_order())
        except CycleError as error:
            raise ValueError(f'Routing cycle: {error.args[1]}') from error


class ArrangementDocument(Document):
    kind: Literal['arrangement'] = 'arrangement'
    timebases: list[Timebase] = Field(min_length=1, max_length=1)
    body: Arrangement
    destinations: list[FileDestination] = Field(default_factory=list)

    @model_validator(mode='after')
    def audio_clock(self) -> Self:
        ports = {o.id for o in self.body.outputs}
        if any(d.port not in ports for d in self.destinations):
            raise ValueError('Destination references an unknown output port')
        clock = self.timebases[0]
        if any(
            n.stream.timebase != clock.id for n in [*self.body.tracks, *self.body.buses]
        ):
            raise ValueError('audio port references an unknown timebase')
        if self.body.timebase != clock.id:
            raise ValueError('arrangement references an unknown timebase')
        if clock.rate.denominator != 1:
            raise ValueError(
                'audio arrangement rate must be integer samples per second'
            )
        return self
