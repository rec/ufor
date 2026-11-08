"""Portable acyclic audio-effect graphs and prepared effect actions."""

from enum import StrEnum, auto
from graphlib import CycleError, TopologicalSorter
from math import cos, fsum, pi, sin, sqrt
from typing import Annotated, ClassVar, Literal, Self, cast

from pydantic import Field, StrictBool, TypeAdapter, model_validator
from reccy.configuration import units

from . import modulation
from .assets import is_finite_audio_source
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
from .oscillator import Waveform
from .samples.instrument import AudioAsset
from .samples.processing import (
    FollowerBinding,
    GeneratorBinding,
    ModulationSettings,
    ResonantFilter,
)
from .time import Timebase

BYPASS_FADE_FRAMES = 64
TAIL_RETIREMENT_FADE_FRAMES = 64
DECAYING_STATE_FLOOR = 1e-30
FILTER_TAIL_THRESHOLD = 1e-12
FREEZE_CROSSFADE_FRAMES = 64
DELAY_RETIME_FADE_FRAMES = 64
WAVESHAPER_LATENCY_FRAMES = 48


def default_grain_duration(data: dict[str, object]) -> float:
    """Reserve the larger of the authored output duration and input history."""
    return max(
        cast(float, data['duration_seconds']), cast(float, data['history_seconds'])
    )


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
    gain_db: Annotated[FiniteScalar, units.unit_validator('decibel')] = 0.0
    mix: UnitInterval = 1.0
    bypass_fade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=BYPASS_FADE_FRAMES, ge=1, strict=True
    )


class Waveshaper(Model):
    """Four-times oversampled hard/soft/fold curves with zero-preserving bias."""

    kind: Literal['waveshaper'] = 'waveshaper'
    name: Identifier
    curve: Literal['hard', 'soft', 'fold'] = 'soft'
    drive: Positive = 1.0
    bias: FiniteScalar = 0.0
    output_gain_db: Annotated[FiniteScalar, units.unit_validator('decibel')] = 0.0
    mix: UnitInterval = 1.0
    bypass_fade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=BYPASS_FADE_FRAMES, ge=1, strict=True
    )


class Phaser(Model):
    """Six identical all-pass stages with an external bipolar sweep control."""

    kind: Literal['phaser'] = 'phaser'
    name: Identifier
    center_hz: Frequency = 800.0
    depth_cents: Annotated[FiniteScalar, units.unit_validator('musical_cent')] = Field(
        default=2400.0, ge=0
    )
    sweep: FiniteScalar = Field(default=0.0, ge=-1, le=1)
    feedback: FiniteScalar = Field(default=0.0, ge=-0.95, le=0.95)
    mix: UnitInterval = 0.5
    bypass_fade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=BYPASS_FADE_FRAMES, ge=1, strict=True
    )
    tail_threshold: Positive = FILTER_TAIL_THRESHOLD
    state_floor: Positive = DECAYING_STATE_FLOOR

    @model_validator(mode='after')
    def decaying_state(self) -> Self:
        if self.state_floor >= self.tail_threshold:
            raise ValueError('phaser state_floor must be below tail_threshold')
        return self


class Follower(Model):
    """Linked peak analysis with frame-invariant attack/release smoothing."""

    kind: Literal['follower'] = 'follower'
    name: Identifier
    attack_seconds: Seconds = 0.01
    release_seconds: Seconds = 0.1
    tail_threshold: Positive = FILTER_TAIL_THRESHOLD
    state_floor: Positive = DECAYING_STATE_FLOOR

    @model_validator(mode='after')
    def decaying_state(self) -> Self:
        if self.state_floor >= self.tail_threshold:
            raise ValueError('follower state_floor must be below tail_threshold')
        return self


class MixerInput(Model):
    name: Identifier
    gain_db: Annotated[FiniteScalar, units.unit_validator('decibel')] = 0.0
    muted: StrictBool = False
    solo: StrictBool = False


class Mixer(Model):
    """Explicit named inputs, with continuously retimed mute/solo fades."""

    kind: Literal['mixer'] = 'mixer'
    name: Identifier
    inputs: list[MixerInput] = Field(min_length=1)
    switch_fade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=64, ge=1, strict=True
    )

    @model_validator(mode='after')
    def unique_inputs(self) -> Self:
        unique((i.name for i in self.inputs), 'mixer input')
        return self


class Crossfader(Model):
    kind: Literal['crossfader'] = 'crossfader'
    name: Identifier
    law: Literal['linear', 'equal_power']
    position: UnitInterval = 0.5


class ChannelMatrix(Model):
    """Always-applied named-channel routing with explicit linear coefficients."""

    kind: Literal['matrix'] = 'matrix'
    name: Identifier
    input_channels: list[Identifier] = Field(min_length=1)
    output_channels: list[Identifier] = Field(min_length=1)
    coefficients: list[list[FiniteScalar]] = Field(min_length=1)

    @model_validator(mode='after')
    def matrix_shape(self) -> Self:
        unique(self.input_channels, 'matrix input channel')
        unique(self.output_channels, 'matrix output channel')
        if len(self.coefficients) != len(self.output_channels) or any(
            len(r) != len(self.input_channels) for r in self.coefficients
        ):
            raise ValueError('matrix rows/columns must match output/input channels')
        return self


class ConvolutionKernel(Model):
    input_channel: Identifier
    output_channel: Identifier
    asset: Identifier
    channel: Identifier


class Convolution(Model):
    """Always-wet named matrix FIR with uniform partition latency."""

    kind: Literal['convolution'] = 'convolution'
    name: Identifier
    input_channels: list[Identifier] = Field(min_length=1)
    output_channels: list[Identifier] = Field(min_length=1)
    kernels: list[ConvolutionKernel] = Field(min_length=1)
    partition_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=256, ge=1, strict=True
    )

    @model_validator(mode='after')
    def named_kernels(self) -> Self:
        unique(self.input_channels, 'convolution input channel')
        unique(self.output_channels, 'convolution output channel')
        unique(
            ((k.input_channel, k.output_channel) for k in self.kernels),
            'convolution channel pair',
        )
        if self.partition_frames & (self.partition_frames - 1):
            raise ValueError('convolution partition_frames must be a power of two')
        if any(
            k.input_channel not in self.input_channels
            or k.output_channel not in self.output_channels
            for k in self.kernels
        ):
            raise ValueError(
                'convolution kernels require declared input/output channels'
            )
        return self


class Highpass(Model):
    """One-pole highpass and DC removal, normalized at Nyquist."""

    kind: Literal['highpass'] = 'highpass'
    name: Identifier
    cutoff_hz: Frequency = 20.0
    mix: UnitInterval = 1.0
    bypass_fade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=BYPASS_FADE_FRAMES, ge=1, strict=True
    )
    tail_threshold: Positive = FILTER_TAIL_THRESHOLD
    state_floor: Positive = DECAYING_STATE_FLOOR

    @model_validator(mode='after')
    def decaying_state(self) -> Self:
        if self.state_floor >= self.tail_threshold:
            raise ValueError('highpass state_floor must be below tail_threshold')
        return self


class Gate(Model):
    """Linked peak gate with hysteresis, frame-ceiled hold and no look-ahead."""

    kind: Literal['gate'] = 'gate'
    name: Identifier
    threshold_db: Annotated[FiniteScalar, units.unit_validator('decibel')] = -40.0
    hysteresis_db: Annotated[FiniteScalar, units.unit_validator('decibel')] = Field(
        default=6.0, ge=0
    )
    hold_seconds: Seconds = 0.01
    attack_seconds: Seconds = 0.001
    release_seconds: Seconds = 0.05
    mix: UnitInterval = 1.0
    bypass_fade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=BYPASS_FADE_FRAMES, ge=1, strict=True
    )


class Expander(Model):
    """Linked peak, hard-knee downward expansion without look-ahead."""

    kind: Literal['expander'] = 'expander'
    name: Identifier
    threshold_db: Annotated[FiniteScalar, units.unit_validator('decibel')] = -40.0
    ratio: FiniteScalar = Field(default=2.0, ge=1)
    attack_seconds: Seconds = 0.001
    release_seconds: Seconds = 0.05
    mix: UnitInterval = 1.0
    bypass_fade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=BYPASS_FADE_FRAMES, ge=1, strict=True
    )


class Compressor(Model):
    """Linked peak, feed-forward compression with an explicit detector port."""

    kind: Literal['compressor'] = 'compressor'
    name: Identifier
    threshold_db: Annotated[FiniteScalar, units.unit_validator('decibel')] = -18.0
    ratio: FiniteScalar = Field(default=4.0, ge=1)
    knee_db: Annotated[FiniteScalar, units.unit_validator('decibel')] = Field(
        default=6.0, ge=0
    )
    attack_seconds: Seconds = 0.01
    release_seconds: Seconds = 0.1
    makeup_db: Annotated[FiniteScalar, units.unit_validator('decibel')] = 0.0
    mix: UnitInterval = 1.0
    bypass_fade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=BYPASS_FADE_FRAMES, ge=1, strict=True
    )


class Reverb(Model):
    """Eight-line feedback-delay-network profile with named stereo output."""

    kind: Literal['reverb'] = 'reverb'
    name: Identifier
    predelay_seconds: Seconds = 0.0
    maximum_predelay_seconds: Seconds = 0.25
    decay_seconds: PositiveSeconds = 2.0
    damping_hz: Frequency = 6000.0
    retime_fade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=DELAY_RETIME_FADE_FRAMES, ge=1, strict=True
    )
    mix: UnitInterval = 0.25
    bypass_fade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=BYPASS_FADE_FRAMES, ge=1, strict=True
    )
    tail_threshold: Positive = FILTER_TAIL_THRESHOLD
    state_floor: Positive = DECAYING_STATE_FLOOR

    @model_validator(mode='after')
    def bounded_predelay(self) -> Self:
        if self.predelay_seconds > self.maximum_predelay_seconds:
            raise ValueError('reverb predelay exceeds its prepared maximum')
        if self.state_floor >= self.tail_threshold:
            raise ValueError('reverb state_floor must be below tail_threshold')
        return self


class DelayTap(Model):
    """Named authoring settings expanded by multitap_graph into ordinary nodes."""

    name: Identifier
    delay_seconds: PositiveSeconds
    maximum_delay_seconds: PositiveSeconds
    gain_db: Annotated[FiniteScalar, units.unit_validator('decibel')] = -6.0
    pan: FiniteScalar = Field(default=0.0, ge=-1, le=1)

    @model_validator(mode='after')
    def bounded_delay(self) -> Self:
        if self.delay_seconds > self.maximum_delay_seconds:
            raise ValueError('tap exceeds its prepared maximum delay')
        return self


class DelaySettings(Model):
    """Shared bounded fixed-delay settings."""

    name: Identifier
    delay_seconds: PositiveSeconds
    maximum_delay_seconds: PositiveSeconds
    feedback: float = Field(default=0.0, ge=0, lt=1)
    damping_hz: Frequency | None = None
    retime_fade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=DELAY_RETIME_FADE_FRAMES, ge=1, strict=True
    )
    mix: UnitInterval = 1.0
    bypass_fade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=BYPASS_FADE_FRAMES, ge=1, strict=True
    )
    tail_threshold: Positive = FILTER_TAIL_THRESHOLD
    state_floor: Positive = DECAYING_STATE_FLOOR

    @model_validator(mode='after')
    def bounded_delay(self) -> Self:
        if self.delay_seconds > self.maximum_delay_seconds:
            raise ValueError('tap delay exceeds its prepared maximum delay')
        if self.state_floor >= self.tail_threshold:
            raise ValueError('tap delay state_floor must be below tail_threshold')
        return self


class TapDelay(DelaySettings):
    """Fractional fixed taps with independent channel feedback."""

    kind: Literal['tap_delay'] = 'tap_delay'


class MatrixDelay(DelaySettings):
    """Fixed taps with static cross-channel feedback, rows as destinations."""

    kind: Literal['matrix_delay'] = 'matrix_delay'
    feedback_matrix: list[list[Annotated[FiniteScalar, Field(ge=-1, le=1)]]] = Field(
        min_length=1
    )

    @model_validator(mode='after')
    def bounded_feedback_matrix(self) -> Self:
        size = len(self.feedback_matrix)
        if any(len(r) != size for r in self.feedback_matrix):
            raise ValueError('delay feedback matrix must be square')
        if any(fsum(abs(v) for v in r) > 1 for r in self.feedback_matrix):
            raise ValueError('delay feedback matrix absolute row sums exceed one')
        return self


class ResonantDelay(Model):
    """Fixed-tuning, input-excited resonator with nominal undamped T60."""

    kind: Literal['resonant_delay'] = 'resonant_delay'
    name: Identifier
    frequency_hz: Frequency
    damping_hz: Frequency = 6000.0
    decay_seconds: PositiveSeconds = 1.0
    mix: UnitInterval = 1.0
    bypass_fade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=BYPASS_FADE_FRAMES, ge=1, strict=True
    )
    tail_threshold: Positive = FILTER_TAIL_THRESHOLD
    state_floor: Positive = DECAYING_STATE_FLOOR

    @model_validator(mode='after')
    def bounded_state_floor(self) -> Self:
        if self.state_floor >= self.tail_threshold:
            raise ValueError('resonant delay state_floor must be below tail_threshold')
        return self


class ModulatedDelay(Model):
    """One bounded, linearly interpolated moving read for chorus and flanger."""

    kind: Literal['modulated_delay'] = 'modulated_delay'
    name: Identifier
    base_delay_seconds: PositiveSeconds
    depth_seconds: Seconds = 0.0
    maximum_delay_seconds: PositiveSeconds
    rate_hz: Frequency
    waveform: Waveform = Waveform.sine
    channel_phase_offsets: list[UnitInterval] = Field(default_factory=list)
    feedback: float = Field(default=0.0, ge=0, lt=1)
    mix: UnitInterval = 1.0
    bypass_fade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=BYPASS_FADE_FRAMES, ge=1, strict=True
    )
    tail_threshold: Positive = FILTER_TAIL_THRESHOLD
    state_floor: Positive = DECAYING_STATE_FLOOR

    @model_validator(mode='after')
    def bounded_delay(self) -> Self:
        if self.base_delay_seconds <= self.depth_seconds:
            raise ValueError('modulated delay must retain a positive minimum delay')
        if self.base_delay_seconds + self.depth_seconds > self.maximum_delay_seconds:
            raise ValueError('modulated delay exceeds its prepared maximum delay')
        if self.state_floor >= self.tail_threshold:
            raise ValueError('modulated delay state_floor must be below tail_threshold')
        return self


class ModulatedTap(Model):
    """A modulated-delay voice and its static stereo placement."""

    delay: ModulatedDelay
    gain_db: Annotated[FiniteScalar, units.unit_validator('decibel')] = -6.0
    pan: FiniteScalar = Field(default=0.0, ge=-1, le=1)


class Filter(Model):
    kind: Literal['filter'] = 'filter'
    name: Identifier
    filters: list[ResonantFilter] = Field(min_length=1)
    mix: UnitInterval = 1.0
    bypass_fade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=BYPASS_FADE_FRAMES, ge=1, strict=True
    )
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
    bypass_fade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=BYPASS_FADE_FRAMES, ge=1, strict=True
    )


class Granulator(Model):
    kind: Literal['granulator'] = 'granulator'
    name: Identifier
    duration_seconds: PositiveSeconds
    density_hz: Frequency
    lookback_seconds: Seconds = 0.0
    playback_ratio: Positive = 1.0
    position_jitter_seconds: Seconds = 0.0
    history_seconds: PositiveSeconds
    maximum_duration_seconds: PositiveSeconds = Field(
        default_factory=default_grain_duration
    )
    maximum_grains: int = Field(ge=1, strict=True)
    mix: UnitInterval = 1.0
    bypass_fade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=BYPASS_FADE_FRAMES, ge=1, strict=True
    )
    freeze_crossfade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=FREEZE_CROSSFADE_FRAMES, ge=1, strict=True
    )

    @model_validator(mode='after')
    def retained_history(self) -> Self:
        if self.duration_seconds > self.maximum_duration_seconds:
            raise ValueError('granulator duration exceeds its prepared maximum')
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
    Gain
    | Waveshaper
    | Phaser
    | Highpass
    | ChannelMatrix
    | Convolution
    | Mixer
    | Crossfader
    | Follower
    | Compressor
    | Gate
    | Expander
    | Reverb
    | TapDelay
    | MatrixDelay
    | ResonantDelay
    | ModulatedDelay
    | Filter
    | Multiply
    | Granulator,
    Field(discriminator='kind'),
]


class EffectGraph(ModulationSettings):
    follower_bindings: ClassVar[bool] = True

    scope: AttachmentScope
    owner: Identifier | None = None
    inputs: list[GraphInput] = Field(min_length=1)
    processors: list[Processor] = Field(min_length=1)
    connections: list[Connection] = Field(min_length=1)
    output: AudioSource
    timebases: list[Timebase] = Field(default_factory=list)
    assets: list[AudioAsset] = Field(default_factory=list)
    maximum_block_frames: Annotated[int, units.unit_validator('frame')] = Field(
        ge=1, strict=True
    )
    maximum_voices: int = Field(default=1, ge=1, strict=True)
    maximum_tails: int = Field(default=1, ge=1, strict=True)
    maximum_action_batches: int = Field(default=64, ge=1, strict=True)
    maximum_actions_per_batch: int = Field(default=16, ge=1, strict=True)
    maximum_actions_per_frame: int = Field(default=64, ge=1, strict=True)
    scheduling_lead_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=1, ge=1, strict=True
    )
    tail_retirement_fade_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=TAIL_RETIREMENT_FADE_FRAMES, ge=1, strict=True
    )

    @model_validator(mode='after')
    def valid_graph(self) -> Self:
        unique((t.name for t in self.timebases), 'effect timebase ID')
        unique((a.name for a in self.assets), 'effect asset ID')
        clocks = {t.name for t in self.timebases}
        assets = {a.name: a for a in self.assets}
        if any(a.audio.timebase not in clocks for a in self.assets):
            raise ValueError('effect asset requires a declared local timebase')
        for processor in self.processors:
            if isinstance(processor, Convolution):
                for kernel in processor.kernels:
                    if kernel.asset not in assets:
                        raise ValueError(f'unknown convolution asset {kernel.asset}')
                    asset = assets[kernel.asset]
                    if (
                        not is_finite_audio_source(asset.location)
                        or asset.audio.frames is None
                        or asset.audio.frames <= 0
                    ):
                        raise ValueError(
                            'convolution requires finite nonempty impulse assets'
                        )
                    if kernel.channel not in asset.audio.channels:
                        raise ValueError(f'unknown impulse channel {kernel.channel}')
        if any(
            not isinstance(b, (GeneratorBinding, FollowerBinding))
            for b in self.bindings
        ):
            raise ValueError('Effect modulation requires Envelfo or follower bindings')
        if any(g.scope != 'voice' for g in self.envelfos.values()):
            raise ValueError('Effect generators use voice scope for one graph instance')
        if any(p.scope != 'voice' for p in self.modulation.parameters):
            raise ValueError('Effect parameters belong to one graph instance')
        processors = {p.name: p for p in self.processors}
        for binding in self.bindings:
            if isinstance(binding, FollowerBinding) and not isinstance(
                processors.get(binding.processor), Follower
            ):
                raise ValueError('Follower binding requires a follower processor')
        for parameter in self.modulation.parameters:
            processor = processors[parameter.target.name]
            for value in (parameter.minimum, parameter.maximum):
                validate_parameter(processor, parameter.target.parameter, value)
        domains = {
            (p.target.name, p.target.parameter): (p.minimum, p.maximum)
            for p in self.modulation.parameters
        }
        for processor in self.processors:
            if isinstance(processor, ModulatedDelay):
                base = domains.get(
                    (processor.name, 'base_delay_seconds'),
                    (processor.base_delay_seconds,) * 2,
                )
                depth = domains.get(
                    (processor.name, 'depth_seconds'), (processor.depth_seconds,) * 2
                )
                if (
                    base[0] <= depth[1]
                    or base[1] + depth[1] > processor.maximum_delay_seconds
                ):
                    raise ValueError(
                        'modulation domains exceed the prepared delay span'
                    )
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
                if isinstance(processors[connection.source.processor], Follower):
                    raise ValueError(
                        'Follower analysis cannot be connected to an audio port'
                    )
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
        dependencies = self.dependencies()
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
            if isinstance(processors[self.output.processor], Follower):
                raise ValueError('Follower analysis cannot be the graph audio output')
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

    def parameter_definition(
        self, target: modulation.Target
    ) -> tuple[modulation.Unit, float]:
        processor = next((p for p in self.processors if p.name == target.name), None)
        if processor is None:
            raise ValueError(f'Unknown processor {target.name}')
        name = target.parameter
        if isinstance(processor, Mixer):
            for definition in processor.inputs:
                if name == f'{definition.name}-gain_db':
                    return modulation.Unit.db, definition.gain_db
        if isinstance(processor, Filter):
            for definition in processor.filters:
                if name == f'{definition.name}-cutoff_hz':
                    return modulation.Unit.hz, definition.cutoff_hz
                if name == f'{definition.name}-q':
                    return modulation.Unit.ratio, definition.q
        value = getattr(processor, name, None)
        if not isinstance(value, (int, float)):
            raise ValueError(f'Unknown effect parameter {target.name}.{name}')
        validate_parameter(processor, name, value)
        unit = (
            modulation.Unit.db
            if name.endswith('_db')
            else modulation.Unit.cents
            if name.endswith('_cents')
            else modulation.Unit.seconds
            if name.endswith('_seconds')
            else modulation.Unit.hz
            if name.endswith('_hz')
            else modulation.Unit.ratio
        )
        return unit, float(value)

    def dependencies(self) -> dict[str, set[str]]:
        dependencies = {p.name: set() for p in self.processors}
        for connection in self.connections:
            if isinstance(connection.source, ProcessorSource):
                dependencies[connection.processor].add(connection.source.processor)
        followers = {
            b.name: b.processor for b in self.bindings if isinstance(b, FollowerBinding)
        }
        for route in self.modulation.routes:
            if route.source in followers:
                dependencies[route.target.name].add(followers[route.source])
        return dependencies

    def order(self) -> list[Identifier]:
        return stable_order(self.processors, self.dependencies())

    def latencies(self) -> dict[str, int]:
        """Output latency per processor after aligning all of its input ports."""
        processors = {p.name: p for p in self.processors}
        dependencies = self.dependencies()
        result: dict[str, int] = {}
        for name in self.order():
            processor = processors[name]
            result[name] = max(
                (result[d] for d in dependencies[name]), default=0
            ) + processor_latency(processor)
        return result

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
    duration_frames: Annotated[int, units.unit_validator('frame')] = Field(
        default=0, ge=0, strict=True
    )

    @model_validator(mode='before')
    @classmethod
    def parameter_units(cls, value: object) -> object:
        if not isinstance(value, dict) or not isinstance(value.get('value'), str):
            return value
        parameter = value.get('parameter')
        if not isinstance(parameter, str):
            return value
        unit = {
            'gain_db': 'decibel',
            'threshold_db': 'decibel',
            'hysteresis_db': 'decibel',
            'knee_db': 'decibel',
            'makeup_db': 'decibel',
            'output_gain_db': 'decibel',
            'ratio': 'dimensionless',
            'attack_seconds': 'second',
            'release_seconds': 'second',
            'hold_seconds': 'second',
            'predelay_seconds': 'second',
            'decay_seconds': 'second',
            'damping_hz': 'hertz',
            'center_hz': 'hertz',
            'cutoff_hz': 'hertz',
            'depth_cents': 'musical_cent',
            'delay_seconds': 'second',
            'base_delay_seconds': 'second',
            'depth_seconds': 'second',
            'duration_seconds': 'second',
            'rate_hz': 'hertz',
            'density_hz': 'hertz',
            'mix': 'dimensionless',
            'position': 'dimensionless',
            'drive': 'dimensionless',
            'feedback': 'dimensionless',
            'playback_ratio': 'dimensionless',
        }.get(parameter.rsplit('-', 1)[-1])
        if unit is None:
            return value
        return dict(value) | {
            'value': TypeAdapter(
                Annotated[FiniteScalar, units.unit_validator(unit)]
            ).validate_python(value['value'])
        }


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
        if isinstance(processor, ChannelMatrix):
            raise ValueError(
                'routing matrices have no parameter, bypass or freeze actions'
            )
        if isinstance(processor, Convolution):
            raise ValueError(
                'convolution is always wet; control mix through routing nodes'
            )
        if isinstance(action, ParameterAction):
            validate_parameter(processor, action.parameter, action.value)
            if (
                isinstance(processor, Mixer)
                and action.parameter.rsplit('-', 1)[-1] in {'muted', 'solo'}
                and action.duration_frames
            ):
                raise ValueError(
                    'mixer selectors are immediate requests with internal fades'
                )
        elif isinstance(action, BypassAction) and isinstance(
            processor, (Mixer, Crossfader, Follower)
        ):
            raise ValueError('mixers, crossfaders and followers have no bypass')
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
    if isinstance(processor, Mixer):
        return {i.name for i in processor.inputs}
    if isinstance(processor, Crossfader):
        return {'first', 'second'}
    if isinstance(processor, (Compressor, Gate, Expander)):
        return {'input', 'detector'}
    return {'carrier', 'modulator'} if isinstance(processor, Multiply) else {'input'}


def polarity_matrix(name: Identifier, channels: list[Identifier]) -> ChannelMatrix:
    return ChannelMatrix(
        name=name,
        input_channels=channels,
        output_channels=channels,
        coefficients=[
            [-1.0 if i == j else 0.0 for j in range(len(channels))]
            for i in range(len(channels))
        ],
    )


def pan_matrix(name: Identifier, pan: float) -> ChannelMatrix:
    if not -1 <= pan <= 1:
        raise ValueError('pan must be in [-1, 1]')
    angle = (pan + 1) * pi / 4
    return ChannelMatrix(
        name=name,
        input_channels=['mono'],
        output_channels=['left', 'right'],
        coefficients=[[cos(angle) if pan != 1 else 0.0], [sin(angle)]],
    )


def balance_matrix(name: Identifier, balance: float) -> ChannelMatrix:
    if not -1 <= balance <= 1:
        raise ValueError('balance must be in [-1, 1]')
    return ChannelMatrix(
        name=name,
        input_channels=['left', 'right'],
        output_channels=['left', 'right'],
        coefficients=[[1 - max(0, balance), 0], [0, 1 + min(0, balance)]],
    )


def width_matrix(name: Identifier, width: float) -> ChannelMatrix:
    if not 0 <= width <= 2:
        raise ValueError('width must be in [0, 2]')
    same, cross = (1 + width) / 2, (1 - width) / 2
    return ChannelMatrix(
        name=name,
        input_channels=['left', 'right'],
        output_channels=['left', 'right'],
        coefficients=[[same, cross], [cross, same]],
    )


def mid_side_matrix(name: Identifier, decode: bool = False) -> ChannelMatrix:
    source, target = ['left', 'right'], ['mid', 'side']
    if decode:
        source, target = target, source
    return ChannelMatrix(
        name=name,
        input_channels=source,
        output_channels=target,
        coefficients=[[1 / sqrt(2), 1 / sqrt(2)], [1 / sqrt(2), -1 / sqrt(2)]],
    )


def multitap_graph(
    name: Identifier,
    scope: AttachmentScope,
    input: GraphInput,
    taps: list[DelayTap],
    maximum_block_frames: int,
    dry_gain_db: float = 0.0,
    owner: Identifier | None = None,
) -> EffectGraph:
    """Compose bounded, independently retimed taps with static stereo placement."""
    if not taps:
        raise ValueError('multitap requires at least one tap')
    unique((t.name for t in taps), 'tap name')
    if len(input.channels) != 1 and input.channels != ['left', 'right']:
        raise ValueError('multitap requires mono or named left/right stereo input')
    source = InputSource(input=input.name)
    dry = (
        pan_matrix(f'{name}-dry', 0).model_copy(
            update={'input_channels': input.channels}
        )
        if len(input.channels) == 1
        else balance_matrix(f'{name}-dry', 0)
    )
    processors: list[Processor] = [dry]
    connections = [
        Connection(processor=dry.name, port='input', source=source),
        Connection(
            processor=name, port='dry', source=ProcessorSource(processor=dry.name)
        ),
    ]
    for tap in taps:
        delay = TapDelay(
            name=f'{name}-tap-{tap.name}',
            delay_seconds=tap.delay_seconds,
            maximum_delay_seconds=tap.maximum_delay_seconds,
        )
        placement = (
            pan_matrix(f'{name}-pan-{tap.name}', tap.pan).model_copy(
                update={'input_channels': input.channels}
            )
            if len(input.channels) == 1
            else balance_matrix(f'{name}-pan-{tap.name}', tap.pan)
        )
        processors.extend([delay, placement])
        connections.extend(
            [
                Connection(processor=delay.name, port='input', source=source),
                Connection(
                    processor=placement.name,
                    port='input',
                    source=ProcessorSource(processor=delay.name),
                ),
                Connection(
                    processor=name,
                    port=f'tap-{tap.name}',
                    source=ProcessorSource(processor=placement.name),
                ),
            ]
        )
    processors.append(
        Mixer(
            name=name,
            inputs=[
                MixerInput(name='dry', gain_db=dry_gain_db),
                *[MixerInput(name=f'tap-{t.name}', gain_db=t.gain_db) for t in taps],
            ],
        )
    )
    return EffectGraph(
        scope=scope,
        owner=owner,
        inputs=[input],
        processors=processors,
        connections=connections,
        output=ProcessorSource(processor=name),
        maximum_block_frames=maximum_block_frames,
    )


def modulated_multitap_graph(
    name: Identifier,
    scope: AttachmentScope,
    input: GraphInput,
    taps: list[ModulatedTap],
    maximum_block_frames: int,
    dry_gain_db: float = 0.0,
    owner: Identifier | None = None,
) -> EffectGraph:
    """Compose authored doubling, ensemble and ADT voices from existing nodes."""
    graph = multitap_graph(
        name,
        scope,
        input,
        [
            DelayTap(
                name=t.delay.name,
                delay_seconds=t.delay.base_delay_seconds,
                maximum_delay_seconds=t.delay.maximum_delay_seconds,
                gain_db=t.gain_db,
                pan=t.pan,
            )
            for t in taps
        ],
        maximum_block_frames,
        dry_gain_db,
        owner,
    )
    delays = {
        f'{name}-tap-{t.delay.name}': t.delay.model_copy(
            update={'name': f'{name}-tap-{t.delay.name}'}
        )
        for t in taps
    }
    return EffectGraph.model_validate(
        {
            **graph.model_dump(),
            'processors': [
                delays.get(p.name, p).model_dump() for p in graph.processors
            ],
        }
    )


def processor_channels(
    processor: Processor, port_layouts: dict[str, list[str]]
) -> list[str]:
    if isinstance(processor, MatrixDelay) and len(processor.feedback_matrix) != len(
        port_layouts['input']
    ):
        raise ValueError('delay feedback matrix must match its input channel count')
    if isinstance(processor, Follower):
        return ['level']
    if isinstance(processor, (Mixer, Crossfader)):
        ports = (
            [i.name for i in processor.inputs]
            if isinstance(processor, Mixer)
            else ['first', 'second']
        )
        layout = port_layouts[ports[0]]
        if any(port_layouts[p] != layout for p in ports[1:]):
            raise ValueError(
                'mixer and crossfader inputs require matching named layouts'
            )
        return layout
    if isinstance(processor, Convolution):
        if port_layouts['input'] != processor.input_channels:
            raise ValueError('convolution input layout must match its source')
        return processor.output_channels
    if isinstance(processor, ChannelMatrix):
        if port_layouts['input'] != processor.input_channels:
            raise ValueError('matrix input channel layout must match its source')
        return processor.output_channels
    if isinstance(processor, Reverb):
        if len(port_layouts['input']) != 1 and port_layouts['input'] != [
            'left',
            'right',
        ]:
            raise ValueError('reverb requires mono or named left/right stereo input')
        return ['left', 'right']
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


def processor_latency(processor: Processor) -> int:
    if isinstance(processor, Waveshaper):
        return WAVESHAPER_LATENCY_FRAMES
    if isinstance(processor, Convolution):
        return processor.partition_frames
    return 0


def validate_parameter(processor: Processor, parameter: str, value: float) -> None:
    if isinstance(processor, Convolution):
        raise ValueError('convolution is always wet; control mix through routing nodes')
    if isinstance(processor, ChannelMatrix):
        raise ValueError('routing matrices have no parameters')
    if isinstance(processor, Mixer):
        for definition in processor.inputs:
            if parameter == f'{definition.name}-gain_db':
                return
            if parameter in {f'{definition.name}-muted', f'{definition.name}-solo'}:
                if value not in (0, 1):
                    raise ValueError('mixer selectors must be zero or one')
                return
        raise ValueError(f'unknown mixer parameter {parameter}')
    if isinstance(processor, Crossfader):
        if parameter != 'position' or not 0 <= value <= 1:
            raise ValueError('crossfader position must be in [0, 1]')
        return
    if isinstance(processor, (Gate, Expander)):
        if parameter == 'threshold_db':
            return
        if (
            parameter in {'attack_seconds', 'release_seconds'}
            or isinstance(processor, Gate)
            and parameter in {'hysteresis_db', 'hold_seconds'}
        ):
            if value < 0:
                raise ValueError(
                    'gate/expander times and hysteresis must be nonnegative'
                )
            return
        if isinstance(processor, Expander) and parameter == 'ratio':
            if value < 1:
                raise ValueError('expander ratio must be at least one')
            return
    if isinstance(processor, Follower):
        if parameter not in {'attack_seconds', 'release_seconds'} or value < 0:
            raise ValueError('follower attack/release must be nonnegative')
        return
    if parameter == 'mix':
        if not 0 <= value <= 1:
            raise ValueError('mix must be in [0, 1]')
        return
    if isinstance(processor, Gain) and parameter == 'gain_db':
        return
    if isinstance(processor, Highpass) and parameter == 'cutoff_hz':
        if value <= 0:
            raise ValueError('highpass cutoff must be positive')
        return
    if isinstance(processor, Waveshaper):
        if parameter == 'drive':
            if value <= 0:
                raise ValueError('drive must be positive')
            return
        if parameter in {'bias', 'output_gain_db'}:
            return
    if isinstance(processor, Phaser):
        if parameter == 'center_hz':
            if value <= 0:
                raise ValueError('phaser center must be positive')
            return
        if parameter == 'depth_cents':
            if value < 0:
                raise ValueError('phaser depth must be nonnegative')
            return
        if parameter == 'sweep':
            if not -1 <= value <= 1:
                raise ValueError('phaser sweep must be in [-1, 1]')
            return
        if parameter == 'feedback':
            if not -0.95 <= value <= 0.95:
                raise ValueError('phaser feedback must be in [-0.95, 0.95]')
            return
    if isinstance(processor, Compressor):
        if parameter in {'threshold_db', 'makeup_db'}:
            return
        if parameter == 'ratio':
            if value < 1:
                raise ValueError('compressor ratio must be at least one')
            return
        if parameter in {'knee_db', 'attack_seconds', 'release_seconds'}:
            if value < 0:
                raise ValueError('compressor knee and times must be nonnegative')
            return
    if isinstance(processor, ResonantDelay) and parameter == 'decay_seconds':
        if value <= 0:
            raise ValueError('resonant decay must be positive')
        return
    if isinstance(processor, Reverb):
        if parameter == 'predelay_seconds':
            if not 0 <= value <= processor.maximum_predelay_seconds:
                raise ValueError(
                    'reverb predelay must remain inside its prepared maximum'
                )
            return
        if parameter in {'decay_seconds', 'damping_hz'}:
            if value <= 0:
                raise ValueError('reverb decay and damping must be positive')
            return
    if isinstance(processor, (TapDelay, MatrixDelay)):
        if parameter == 'damping_hz':
            if processor.damping_hz is None:
                raise ValueError('tap delay damping is not prepared')
            if value <= 0:
                raise ValueError('tap delay damping must be positive')
            return
        if parameter == 'delay_seconds':
            if not 0 < value <= processor.maximum_delay_seconds:
                raise ValueError('delay_seconds must be within the prepared maximum')
            return
        if parameter == 'feedback':
            if not 0 <= value < 1:
                raise ValueError('feedback must be in [0, 1)')
            return
    if isinstance(processor, ModulatedDelay):
        if parameter == 'base_delay_seconds':
            if (
                not processor.depth_seconds
                < value
                <= (processor.maximum_delay_seconds - processor.depth_seconds)
            ):
                raise ValueError(
                    'base_delay_seconds must retain the prepared delay span'
                )
            return
        if parameter == 'depth_seconds':
            if 0 <= value < processor.base_delay_seconds and (
                processor.base_delay_seconds + value <= processor.maximum_delay_seconds
            ):
                return
            raise ValueError('depth_seconds must retain the prepared delay span')
        if parameter == 'rate_hz':
            if value < 0:
                raise ValueError('rate_hz must be nonnegative')
            return
        if parameter == 'feedback':
            if not 0 <= value < 1:
                raise ValueError('feedback must be in [0, 1)')
            return
    if isinstance(processor, Granulator):
        if parameter == 'duration_seconds':
            if not 0 < value <= processor.maximum_duration_seconds:
                raise ValueError(
                    'grain duration must remain inside its prepared maximum'
                )
            return
        if parameter in {'density_hz', 'playback_ratio'}:
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


def reverb_delay_frames(sample_rate: int) -> list[int]:
    """Round the fixed eight-line geometry, retaining at least one frame per line."""
    if sample_rate <= 0:
        raise ValueError('reverb sample rate must be positive')
    return [max(1, round(t * sample_rate)) for t in REVERB_DELAYS_SECONDS]


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


def grain_jitter(counter: int) -> float:
    """Map a launch counter to a deterministic offset in [-1, 1)."""
    if counter < 0:
        raise ValueError('grain jitter counter must be nonnegative')
    mask = (1 << 64) - 1
    value = (counter + 0x9E3779B97F4A7C15) & mask
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & mask
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & mask
    value ^= value >> 31
    return 2 * ((value >> 11) / 2**53) - 1


def _ancestors(name: str, dependencies: dict[str, set[str]]) -> set[str]:
    result = {name}
    pending = [name]
    while pending:
        for dependency in dependencies[pending.pop()]:
            if dependency not in result:
                result.add(dependency)
                pending.append(dependency)
    return result


REVERB_DELAYS_SECONDS = [0.0297, 0.0371, 0.0411, 0.0437, 0.0531, 0.0617, 0.0713, 0.0797]
