from enum import StrEnum, auto
from graphlib import CycleError, TopologicalSorter
from typing import Literal, Self

from pydantic import Field, model_validator

from .base import Identifier, Model, unique
from .interface import (
    Connection,
    Input,
    InputSelection,
    InterfaceScore,
    MixBinding,
    OutputSelection,
    Part,
)
from .references import ParameterTarget
from .streams import AudioType, FileDestination
from .time import Timebase


class Interpolation(StrEnum):
    hold = auto()
    linear = auto()
    equal_power = auto()


class TrackSpec(Model):
    name: Identifier
    stream: AudioType


class BusSpec(Model):
    name: Identifier
    stream: AudioType
    gain: float = 1.0


class ClipSpec(Model):
    name: Identifier
    source: OutputSelection
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


class Arrangement(Model):
    timebase: Identifier
    media_types: list[str] = Field(default_factory=lambda: ['audio'])
    parts: list[Part] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    tracks: list[TrackSpec] = Field(default_factory=list)
    buses: list[BusSpec] = Field(default_factory=list)
    clips: list[ClipSpec] = Field(default_factory=list)
    routes: list[RouteSpec] = Field(default_factory=list)
    automation: list[AutomationSpec] = Field(default_factory=list)

    @model_validator(mode='after')
    def graph_references(self) -> Self:
        for kind, items in (
            ('name', self.parts),
            ('track', self.tracks),
            ('bus', self.buses),
            ('clip', self.clips),
        ):
            unique((i.name for i in items), f'{kind} ID')
        unique((a.target for a in self.automation), 'automation target')
        unique(((r.source, r.destination) for r in self.routes), 'route')
        tracks = {t.name: t.stream for t in self.tracks}
        buses = {b.name: b.stream for b in self.buses}
        if overlap := tracks.keys() & buses.keys():
            raise ValueError(f'Track and bus IDs collide: {sorted(overlap)}')
        streams = tracks | buses
        sources = {n.name for n in self.parts}
        clips = {c.name for c in self.clips}
        routes = {(r.source, r.destination) for r in self.routes}
        for clip in self.clips:
            if clip.source.name not in sources:
                raise ValueError(f'Clip {clip.name}: unknown source {clip.source}')
            if clip.track not in tracks:
                raise ValueError(f'Clip {clip.name}: unknown track {clip.track}')
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
                target.name in clips
                if target.kind == 'clip'
                else target.name in buses
                if target.kind == 'bus'
                else (target.name, target.destination) in routes
            )
            if not valid:
                raise ValueError(f'Unknown automation target {target!r}')
        unique((c.destination for c in self.connections), 'input connection')
        for connection in self.connections:
            if (
                connection.source.name not in sources
                or connection.destination.name not in sources
            ):
                raise ValueError('connection references an unknown part')
        try:
            list(
                TopologicalSorter(
                    {
                        n.name: [
                            c.source.name
                            for c in self.connections
                            if c.destination.name == n.name
                        ]
                        for n in self.parts
                    }
                ).static_order()
            )
        except CycleError as error:
            raise ValueError('Connection cycle') from error
        return self

    @property
    def bus_order(self) -> list[str]:
        buses = {b.name for b in self.buses}
        dependencies = {
            b.name: [
                r.source
                for r in self.routes
                if r.destination == b.name and r.source in buses
            ]
            for b in self.buses
        }
        try:
            return list(TopologicalSorter(dependencies).static_order())
        except CycleError as error:
            raise ValueError(f'Routing cycle: {error.args[1]}') from error


class ArrangementScore(InterfaceScore):
    kind: Literal['arrangement'] = 'arrangement'
    timebases: list[Timebase] = Field(min_length=1, max_length=1)
    body: Arrangement
    destinations: list[FileDestination] = Field(default_factory=list)

    @model_validator(mode='after')
    def audio_clock(self) -> Self:
        outputs = {p.name for p in self.outputs}
        if any(d.output not in outputs for d in self.destinations):
            raise ValueError('Destination references an unknown output')
        parts = {n.name for n in self.body.parts}
        tracks = {t.name: t.stream for t in self.body.tracks}
        buses = {b.name: b.stream for b in self.body.buses}
        forwarded = []
        for point in [*self.inputs, *self.outputs]:
            binding = point.binding
            if isinstance(binding, MixBinding):
                stream = (
                    tracks.get(binding.track)
                    if binding.track is not None
                    else buses.get(binding.bus)
                )
                if stream != point.stream:
                    raise ValueError(
                        'mix export requires a matching output contract '
                        'and existing track/bus'
                    )
            elif isinstance(binding, (InputSelection, OutputSelection)):
                if binding.name not in parts:
                    raise ValueError('binding references an unknown part')
                if isinstance(point, Input):
                    forwarded.append(binding)
            else:
                raise ValueError(
                    'arrangement input/output requires a mix or part binding'
                )
        unique(
            [*forwarded, *(c.destination for c in self.body.connections)],
            'input binding',
        )
        if any(p.binding.name not in parts for p in self.parameters):
            raise ValueError('parameter binding references an unknown part')
        clock = self.timebases[0]
        if any(
            n.stream.timebase != clock.name
            for n in [*self.body.tracks, *self.body.buses]
        ):
            raise ValueError('audio port references an unknown timebase')
        if self.body.timebase != clock.name:
            raise ValueError('arrangement references an unknown timebase')
        if clock.rate.denominator != 1:
            raise ValueError(
                'audio arrangement rate must be integer samples per second'
            )
        return self
