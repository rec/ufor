"""Portable acyclic audio-effect graphs and prepared effect actions."""

from enum import StrEnum, auto
from graphlib import CycleError, TopologicalSorter
from math import cos, pi, sqrt
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from .base import (
    FiniteScalar,
    Frame,
    Frequency,
    Identifier,
    Model,
    Positive,
    PositiveSeconds,
    Seconds,
    UnitInterval,
    unique,
)
from .samples.processing import ResonantFilter

BYPASS_FADE_FRAMES = 64
TAIL_RETIREMENT_FADE_FRAMES = 64
DECAYING_STATE_FLOOR = 1e-30
FILTER_TAIL_THRESHOLD = 1e-12
FREEZE_CROSSFADE_FRAMES = 64


class AttachmentScope(StrEnum):
    voice = auto()
    instrument = auto()
    master = auto()
    host = auto()


class MainStream(Model):
    kind: Literal['main'] = 'main'


class HostStream(Model):
    kind: Literal['host'] = 'host'
    stream: Identifier


class InstrumentStream(Model):
    kind: Literal['instrument'] = 'instrument'
    instrument: Identifier
    tap: Literal['pre_effect', 'post_effect']


StreamSource = Annotated[
    MainStream | HostStream | InstrumentStream, Field(discriminator='kind')
]


class GraphInput(Model):
    name: Identifier
    channels: list[Identifier] = Field(min_length=1)
    source: StreamSource

    @model_validator(mode='after')
    def unique_channels(self) -> Self:
        unique(self.channels, f'channels for graph input {self.name}')
        return self


class InputSource(Model):
    kind: Literal['input'] = 'input'
    input: Identifier


class ProcessorSource(Model):
    kind: Literal['processor'] = 'processor'
    processor: Identifier


AudioSource = Annotated[InputSource | ProcessorSource, Field(discriminator='kind')]


class Connection(Model):
    processor: Identifier
    port: Identifier
    source: AudioSource


class Gain(Model):
    kind: Literal['gain'] = 'gain'
    name: Identifier
    gain_db: FiniteScalar = 0.0
    mix: UnitInterval = 1.0
    bypass_fade_frames: int = Field(default=BYPASS_FADE_FRAMES, ge=1, strict=True)


class Filter(Model):
    kind: Literal['filter'] = 'filter'
    name: Identifier
    filters: list[ResonantFilter] = Field(min_length=1)
    mix: UnitInterval = 1.0
    bypass_fade_frames: int = Field(default=BYPASS_FADE_FRAMES, ge=1, strict=True)
    tail_threshold: Positive = FILTER_TAIL_THRESHOLD
    state_floor: Positive = DECAYING_STATE_FLOOR

    @model_validator(mode='after')
    def filter_names(self) -> Self:
        unique((f.name for f in self.filters), f'filters for processor {self.name}')
        if self.state_floor >= self.tail_threshold:
            raise ValueError('filter state_floor must be below tail_threshold')
        return self


class Multiply(Model):
    kind: Literal['multiply'] = 'multiply'
    name: Identifier
    mix: UnitInterval = 1.0
    bypass_fade_frames: int = Field(default=BYPASS_FADE_FRAMES, ge=1, strict=True)


class Granulator(Model):
    kind: Literal['granulator'] = 'granulator'
    name: Identifier
    duration_seconds: PositiveSeconds
    density_hz: Frequency
    lookback_seconds: Seconds = 0.0
    playback_ratio: Positive = 1.0
    position_jitter_seconds: Seconds = 0.0
    history_seconds: PositiveSeconds
    maximum_grains: int = Field(ge=1, strict=True)
    mix: UnitInterval = 1.0
    bypass_fade_frames: int = Field(default=BYPASS_FADE_FRAMES, ge=1, strict=True)
    freeze_crossfade_frames: int = Field(
        default=FREEZE_CROSSFADE_FRAMES, ge=1, strict=True
    )

    @model_validator(mode='after')
    def retained_history(self) -> Self:
        required = (
            self.lookback_seconds
            + self.position_jitter_seconds
            + self.duration_seconds * self.playback_ratio
        )
        if self.history_seconds < required:
            raise ValueError(
                'granulator history is too short for its maximum read span'
            )
        return self


Processor = Annotated[
    Gain | Filter | Multiply | Granulator, Field(discriminator='kind')
]


class EffectGraph(Model):
    scope: AttachmentScope
    owner: Identifier | None = None
    inputs: list[GraphInput] = Field(min_length=1)
    processors: list[Processor] = Field(min_length=1)
    connections: list[Connection] = Field(min_length=1)
    output: AudioSource
    maximum_block_frames: int = Field(ge=1, strict=True)
    maximum_voices: int = Field(default=1, ge=1, strict=True)
    maximum_tails: int = Field(default=1, ge=1, strict=True)
    maximum_action_batches: int = Field(default=64, ge=1, strict=True)
    maximum_actions_per_batch: int = Field(default=16, ge=1, strict=True)
    maximum_actions_per_frame: int = Field(default=64, ge=1, strict=True)
    scheduling_lead_frames: int = Field(default=1, ge=1, strict=True)
    tail_retirement_fade_frames: int = Field(
        default=TAIL_RETIREMENT_FADE_FRAMES, ge=1, strict=True
    )

    @model_validator(mode='after')
    def valid_graph(self) -> Self:
        if (self.scope in (AttachmentScope.voice, AttachmentScope.master)) != (
            self.owner is None
        ):
            raise ValueError(
                'voice/master graphs omit owner; instrument/host require it'
            )
        unique((i.name for i in self.inputs), 'graph input ID')
        unique((p.name for p in self.processors), 'processor ID')
        unique(((c.processor, c.port) for c in self.connections), 'processor input')
        processors = {p.name: p for p in self.processors}
        inputs = {i.name: i for i in self.inputs}
        if self.scope == AttachmentScope.voice and any(
            not isinstance(i.source, MainStream) for i in self.inputs
        ):
            raise ValueError('per-voice graphs can only consume their own main stream')
        main_count = sum(isinstance(i.source, MainStream) for i in self.inputs)
        if main_count != 1:
            raise ValueError('effect graph requires exactly one main input')
        dependencies: dict[str, set[str]] = {name: set() for name in processors}
        connections: dict[tuple[str, str], Connection] = {}
        for connection in self.connections:
            if connection.processor not in processors:
                raise ValueError(
                    f'unknown destination processor {connection.processor}'
                )
            if connection.port not in processor_ports(processors[connection.processor]):
                raise ValueError(
                    f'unknown port {connection.processor}.{connection.port}'
                )
            if isinstance(connection.source, InputSource):
                if connection.source.input not in inputs:
                    raise ValueError(f'unknown graph input {connection.source.input}')
            else:
                if connection.source.processor not in processors:
                    raise ValueError(
                        f'unknown source processor {connection.source.processor}'
                    )
                dependencies[connection.processor].add(connection.source.processor)
            connections[(connection.processor, connection.port)] = connection
        for processor in self.processors:
            missing = processor_ports(processor) - {
                port for name, port in connections if name == processor.name
            }
            if missing:
                raise ValueError(
                    f'processor {processor.name} has unconnected ports: '
                    f'{sorted(missing)}'
                )
        try:
            tuple(TopologicalSorter(dependencies).static_order())
        except CycleError as error:
            raise ValueError('processor graph contains a cycle') from error
        if isinstance(self.output, InputSource):
            if self.output.input not in inputs:
                raise ValueError(f'unknown graph output input {self.output.input}')
            used: set[str] = set()
        else:
            if self.output.processor not in processors:
                raise ValueError(
                    f'unknown graph output processor {self.output.processor}'
                )
            used = _ancestors(self.output.processor, dependencies)
        if used != processors.keys():
            raise ValueError('every processor must contribute to the graph output')
        layouts: dict[str, list[str]] = {}
        for name in stable_order(self.processors, dependencies):
            processor = processors[name]
            port_layouts = {
                port: source_channels(connections[(name, port)].source, inputs, layouts)
                for port in processor_ports(processor)
            }
            layouts[name] = processor_channels(processor, port_layouts)
        return self

    def order(self) -> list[Identifier]:
        dependencies = {p.name: set() for p in self.processors}
        for connection in self.connections:
            if isinstance(connection.source, ProcessorSource):
                dependencies[connection.processor].add(connection.source.processor)
        return stable_order(self.processors, dependencies)

    def output_channels(self) -> list[Identifier]:
        inputs = {i.name: i for i in self.inputs}
        processors = {p.name: p for p in self.processors}
        connections = {(c.processor, c.port): c for c in self.connections}
        layouts: dict[str, list[str]] = {}
        for name in self.order():
            processor = processors[name]
            layouts[name] = processor_channels(
                processor,
                {
                    port: source_channels(
                        connections[(name, port)].source, inputs, layouts
                    )
                    for port in processor_ports(processor)
                },
            )
        return source_channels(self.output, inputs, layouts)


class ParameterAction(Model):
    kind: Literal['parameter'] = 'parameter'
    tick: Frame
    ordinal: int = Field(ge=0, strict=True)
    processor: Identifier
    parameter: Identifier
    value: FiniteScalar
    duration_frames: int = Field(default=0, ge=0, strict=True)


class BypassAction(Model):
    kind: Literal['bypass'] = 'bypass'
    tick: Frame
    ordinal: int = Field(ge=0, strict=True)
    processor: Identifier
    bypassed: StrictBool


class FreezeAction(Model):
    kind: Literal['freeze'] = 'freeze'
    tick: Frame
    ordinal: int = Field(ge=0, strict=True)
    processor: Identifier
    frozen: StrictBool


class InputEndAction(Model):
    kind: Literal['input_end'] = 'input_end'
    tick: Frame
    ordinal: int = Field(ge=0, strict=True)
    input: Identifier


class StopAction(Model):
    kind: Literal['stop'] = 'stop'
    tick: Frame
    ordinal: int = Field(ge=0, strict=True)


EffectAction = Annotated[
    ParameterAction | BypassAction | FreezeAction | InputEndAction | StopAction,
    Field(discriminator='kind'),
]


class ActionBatch(Model):
    actions: list[EffectAction] = Field(min_length=1)

    @model_validator(mode='after')
    def one_ordered_event(self) -> Self:
        tick = self.actions[0].tick
        if any(a.tick != tick for a in self.actions):
            raise ValueError('an action batch represents one frame event')
        if any(
            b.ordinal <= a.ordinal
            for a, b in zip(self.actions, self.actions[1:], strict=False)
        ):
            raise ValueError('batch action ordinals must strictly increase')
        return self

    @property
    def lifecycle(self) -> bool:
        return any(isinstance(a, (InputEndAction, StopAction)) for a in self.actions)


def validate_action(graph: EffectGraph, action: EffectAction) -> None:
    processors = {p.name: p for p in graph.processors}
    if isinstance(action, (ParameterAction, BypassAction, FreezeAction)):
        if action.processor not in processors:
            raise ValueError(f'unknown processor {action.processor}')
        processor = processors[action.processor]
        if isinstance(action, ParameterAction):
            validate_parameter(processor, action.parameter, action.value)
        elif isinstance(action, FreezeAction) and not isinstance(processor, Granulator):
            raise ValueError('freeze actions require a granulator')
    elif isinstance(action, InputEndAction) and action.input not in {
        i.name for i in graph.inputs
    }:
        raise ValueError(f'unknown graph input {action.input}')


def validate_batch(graph: EffectGraph, batch: ActionBatch) -> None:
    if len(batch.actions) > graph.maximum_actions_per_batch:
        raise ValueError('action batch exceeds graph capacity')
    for action in batch.actions:
        validate_action(graph, action)


def processor_ports(processor: Processor) -> set[str]:
    return {'carrier', 'modulator'} if isinstance(processor, Multiply) else {'input'}


def processor_channels(
    processor: Processor, port_layouts: dict[str, list[str]]
) -> list[str]:
    if isinstance(processor, Multiply):
        if port_layouts['carrier'] != port_layouts['modulator']:
            raise ValueError('multiply inputs require matching channel layouts')
        return port_layouts['carrier']
    return port_layouts['input']


def source_channels(
    source: AudioSource,
    inputs: dict[str, GraphInput],
    processor_layouts: dict[str, list[str]],
) -> list[str]:
    return (
        inputs[source.input].channels
        if isinstance(source, InputSource)
        else processor_layouts[source.processor]
    )


def stable_order(
    processors: list[Processor], dependencies: dict[str, set[str]]
) -> list[Identifier]:
    remaining = {name: set(values) for name, values in dependencies.items()}
    result: list[str] = []
    while remaining:
        ready = sorted(name for name, values in remaining.items() if not values)
        if not ready:
            raise ValueError('processor graph contains a cycle')
        result.extend(ready)
        for name in ready:
            remaining.pop(name)
        for values in remaining.values():
            values.difference_update(ready)
    return result


def validate_parameter(processor: Processor, parameter: str, value: float) -> None:
    if parameter == 'mix':
        if not 0 <= value <= 1:
            raise ValueError('mix must be in [0, 1]')
        return
    if isinstance(processor, Gain) and parameter == 'gain_db':
        return
    if isinstance(processor, Granulator):
        if parameter in {'duration_seconds', 'density_hz', 'playback_ratio'}:
            if value <= 0:
                raise ValueError(f'{parameter} must be positive')
            return
        if parameter in {'lookback_seconds', 'position_jitter_seconds'}:
            if value < 0:
                raise ValueError(f'{parameter} must be nonnegative')
            return
    if isinstance(processor, Filter):
        for definition in processor.filters:
            if parameter == f'{definition.name}-cutoff_hz' and value > 0:
                return
            if parameter == f'{definition.name}-q' and value > 0:
                return
    raise ValueError(f'unsupported parameter {processor.name}.{parameter}')


def grain_window(index: int, frames: int) -> float:
    """Periodic Hann grain window sampled at index in [0, frames)."""
    if frames < 2 or not 0 <= index < frames:
        raise ValueError('grain window requires at least two frames and a valid index')
    return 0.5 - 0.5 * cos(2 * pi * index / frames)


def grain_gain(density_hz: float, duration_seconds: float) -> float:
    """Equal-power overlap gain, latched when a grain starts."""
    if density_hz <= 0 or duration_seconds <= 0:
        raise ValueError('grain density and duration must be positive')
    return 1 / sqrt(max(1.0, density_hz * duration_seconds))


def grain_launches(
    phase: float, density_hz: float, sample_rate: int
) -> tuple[bool, float]:
    """Advance the one-launch-per-frame scheduler before rendering this frame."""
    if not 0 <= phase < 1 or not 0 < density_hz <= sample_rate or sample_rate <= 0:
        raise ValueError('invalid granular scheduler state or density')
    phase += density_hz / sample_rate
    launch = phase >= 1
    return launch, phase - 1 if launch else phase


def _ancestors(name: str, dependencies: dict[str, set[str]]) -> set[str]:
    result = {name}
    pending = [name]
    while pending:
        for dependency in dependencies[pending.pop()]:
            if dependency not in result:
                result.add(dependency)
                pending.append(dependency)
    return result
