from enum import StrEnum, auto
from graphlib import CycleError, TopologicalSorter
from typing import Literal, Self

from pydantic import Field, model_validator

from .base import Identifier, Model, unique
from .interface import (
    Address,
    Connection,
    Direction,
    InterfaceDocument,
    MixBinding,
    Node,
)
from .references import ParameterTarget
from .streams import AudioType, FileDestination
from .time import Timebase


class Interpolation(StrEnum):
    hold = auto()
    linear = auto()
    equal_power = auto()


class TrackSpec(Model):
    id: Identifier
    stream: AudioType


class BusSpec(Model):
    id: Identifier
    stream: AudioType
    gain: float = 1.0


class ClipSpec(Model):
    id: Identifier
    source: Address
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
    nodes: list[Node] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    tracks: list[TrackSpec] = Field(default_factory=list)
    buses: list[BusSpec] = Field(default_factory=list)
    clips: list[ClipSpec] = Field(default_factory=list)
    routes: list[RouteSpec] = Field(default_factory=list)
    automation: list[AutomationSpec] = Field(default_factory=list)

    @model_validator(mode='after')
    def graph_references(self) -> Self:
        for kind, items in (
            ('node', self.nodes),
            ('track', self.tracks),
            ('bus', self.buses),
            ('clip', self.clips),
        ):
            unique((i.id for i in items), f'{kind} ID')
        unique((a.target for a in self.automation), 'automation target')
        unique(((r.source, r.destination) for r in self.routes), 'route')
        tracks = {t.id: t.stream for t in self.tracks}
        buses = {b.id: b.stream for b in self.buses}
        if overlap := tracks.keys() & buses.keys():
            raise ValueError(f'Track and bus IDs collide: {sorted(overlap)}')
        streams = tracks | buses
        sources = {n.id for n in self.nodes}
        clips = {c.id for c in self.clips}
        routes = {(r.source, r.destination) for r in self.routes}
        for clip in self.clips:
            if clip.source.node not in sources:
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
        unique((c.destination for c in self.connections), 'input connection')
        for connection in self.connections:
            if (
                connection.source.node not in sources
                or connection.destination.node not in sources
            ):
                raise ValueError('connection references an unknown node')
        try:
            list(
                TopologicalSorter(
                    {
                        n.id: [
                            c.source.node
                            for c in self.connections
                            if c.destination.node == n.id
                        ]
                        for n in self.nodes
                    }
                ).static_order()
            )
        except CycleError as error:
            raise ValueError('Connection cycle') from error
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


class ArrangementDocument(InterfaceDocument):
    kind: Literal['arrangement'] = 'arrangement'
    timebases: list[Timebase] = Field(min_length=1, max_length=1)
    body: Arrangement
    destinations: list[FileDestination] = Field(default_factory=list)

    @model_validator(mode='after')
    def audio_clock(self) -> Self:
        ports = {p.id for p in self.ports if p.direction == Direction.output}
        if any(d.port not in ports for d in self.destinations):
            raise ValueError('Destination references an unknown output port')
        nodes = {n.id for n in self.body.nodes}
        tracks = {t.id: t.stream for t in self.body.tracks}
        buses = {b.id: b.stream for b in self.body.buses}
        forwarded = []
        for port in self.ports:
            binding = port.binding
            if isinstance(binding, MixBinding):
                stream = (
                    tracks.get(binding.track)
                    if binding.track is not None
                    else buses.get(binding.bus)
                )
                if port.direction != Direction.output or stream != port.stream:
                    raise ValueError(
                        'mix export requires a matching output contract '
                        'and existing track/bus'
                    )
            elif isinstance(binding, Address):
                if binding.node not in nodes:
                    raise ValueError('port binding references an unknown node')
                if port.direction == Direction.input:
                    forwarded.append(binding)
            else:
                raise ValueError('arrangement port requires a mix or child binding')
        unique(
            [*forwarded, *(c.destination for c in self.body.connections)],
            'input binding',
        )
        if any(p.binding.node not in nodes for p in self.parameters):
            raise ValueError('parameter binding references an unknown node')
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
