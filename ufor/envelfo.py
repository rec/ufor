"""Portable definitions for reusable control envelfos."""

from enum import StrEnum, auto
from fractions import Fraction
from functools import cached_property
from graphlib import CycleError, TopologicalSorter
from math import floor, isfinite
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator
from reccy.configuration import units

from . import control
from .base import FiniteScalar, Identifier, Model, UnitInterval, UnitScalar, unique
from .envelope import Retrigger
from .interface import ScoreReference
from .lfo import Reset
from .modulation import Unit, unit_fields, unit_number
from .oscillator import Waveform
from .score import Score
from .segments import Segment


class ParameterReference(Model):
    parameter: Identifier


class EnvelfoParameter(Model):
    unit: Unit
    default: UnitScalar
    minimum: UnitScalar
    maximum: UnitScalar
    description: str | None = None

    @model_validator(mode='before')
    @classmethod
    def declared_units(cls, value: object) -> object:
        return unit_fields(value, ['minimum', 'maximum', 'default'])

    @model_validator(mode='after')
    def domain(self) -> Self:
        if not 0 <= self.minimum <= self.default <= self.maximum:
            raise ValueError('envelfo parameter has an invalid domain or default')
        if self.unit == Unit.hz and self.minimum == 0:
            raise ValueError('Hz envelfo parameters require a positive minimum')
        return self


class EnvelfoOrigin(Model):
    identity: str
    sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')


class Marker(Model):
    name: Identifier
    position: control.Rational = Field(ge=0, le=1)


class Hold(Model):
    kind: Literal['hold'] = 'hold'
    value: FiniteScalar = 0.0


class PlaybackMode(StrEnum):
    once = auto()
    loop = auto()
    ping_pong = auto()


class PositionDriver(StrEnum):
    elapsed = auto()
    transport = auto()


class LFO(Model):
    kind: Literal['lfo'] = 'lfo'
    shape: Waveform = Waveform.sine
    rate: ParameterReference | Annotated[control.Rational, Field(ge=0)]
    phase: Annotated[control.Rational, units.unit_validator('turn', exact=True)] = (
        Field(default=Fraction(0), ge=0, lt=1)
    )
    duty_cycle: control.Rational = Field(default=Fraction(1, 2), ge=0, le=1)
    reset: Reset = Reset.trigger
    delay: control.Rational = Field(default=Fraction(0), ge=0)
    fade_in: control.Rational = Field(default=Fraction(0), ge=0)
    center: FiniteScalar = 0.0
    depth: FiniteScalar = Field(default=1.0, ge=0)
    markers: list[Marker] = Field(default_factory=list)

    @model_validator(mode='after')
    def output_and_markers(self) -> Self:
        if not -1 <= self.center - self.depth <= self.center + self.depth <= 1:
            raise ValueError('LFO output must remain within [-1, 1]')
        if any(m.position == 1 for m in self.markers):
            raise ValueError('LFO marker positions must be less than one')
        unique((m.name for m in self.markers), 'LFO marker')
        return self

    @model_validator(mode='before')
    @classmethod
    def clock_units(cls, value: object) -> object:
        return control.clock_fields(value)


class Envelope(Model):
    kind: Literal['envelope'] = 'envelope'
    initial: FiniteScalar | Literal['current'] = 0.0
    start: Literal['activation', 'event'] = 'activation'
    segments: list[Segment] = Field(min_length=1)
    release: list[Segment] = Field(default_factory=list)
    polarity: control.Polarity = control.Polarity.unipolar
    hold: bool = True
    retrigger: Retrigger = Retrigger.current
    playback: PlaybackMode = PlaybackMode.once
    markers: list[Marker] = Field(default_factory=list)
    loop_start: Identifier | None = None
    loop_end: Identifier | None = None
    repeat_count: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def levels_match_polarity(self) -> Self:
        levels = [
            *(v for v in [self.initial] if isinstance(v, float)),
            *(s.to for s in [*self.segments, *self.release]),
        ]
        if any(not -1 <= value <= 1 for value in levels):
            raise ValueError('envelope levels must be in [-1, 1]')
        if self.polarity == control.Polarity.unipolar and min(levels) < 0:
            raise ValueError('unipolar envelope levels must be in [0, 1]')
        unique((m.name for m in self.markers), 'envelope marker')
        if (self.loop_start is None) != (self.loop_end is None):
            raise ValueError('envelope loop boundaries must be named together')
        if self.loop_start is not None:
            if self.playback == PlaybackMode.once:
                raise ValueError('once envelopes cannot name loop boundaries')
            positions = {m.name: m.position for m in self.markers}
            if self.loop_start not in positions or self.loop_end not in positions:
                raise ValueError('envelope loop boundary marker is unknown')
            if positions[self.loop_start] >= positions[self.loop_end]:
                raise ValueError('envelope loop start must precede its end')
            if any(m.position > positions[self.loop_end] for m in self.markers):
                raise ValueError('envelope markers cannot follow its loop end')
        if self.repeat_count is not None and self.playback == PlaybackMode.once:
            raise ValueError('repeat count requires loop or ping-pong playback')
        return self


class Stage(Model):
    name: Identifier
    envelfo: Annotated[Hold | LFO | Envelope, Field(discriminator='kind')]


class EnterStage(Model):
    kind: Literal['enter'] = 'enter'
    stage: Identifier


class FinishStage(Model):
    kind: Literal['finish'] = 'finish'


class StageTransition(Model):
    from_stages: list[Identifier] = Field(
        min_length=1, validation_alias='from', serialization_alias='from'
    )
    event: str = Field(min_length=1)
    action: Annotated[EnterStage | FinishStage, Field(discriminator='kind')]

    model_config = ConfigDict(serialize_by_alias=True, validate_by_name=True)


class Stages(Model):
    kind: Literal['stages'] = 'stages'
    initial_stage: Identifier
    stages: list[Stage] = Field(min_length=1)
    transitions: list[StageTransition] = Field(default_factory=list)

    @model_validator(mode='after')
    def references(self) -> Self:
        names = {s.name for s in self.stages}
        unique((s.name for s in self.stages), 'stage')
        if self.initial_stage not in names:
            raise ValueError('initial stage is unknown')
        initial = next(s.envelfo for s in self.stages if s.name == self.initial_stage)
        if isinstance(initial, Envelope) and initial.initial == 'current':
            raise ValueError('initial stage cannot capture a current value')
        for stage in self.stages:
            body = stage.envelfo
            if isinstance(body, (LFO, Envelope)) and any(
                m.name == 'done' for m in body.markers
            ):
                raise ValueError('stage marker name done is reserved for completion')
            if isinstance(body, LFO) and isinstance(body.rate, ParameterReference):
                raise ValueError('stage LFO rate must be a literal')
            if isinstance(body, Envelope) and body.start == 'event':
                raise ValueError('stage envelopes start on stage entry')
            if isinstance(body, Envelope) and (
                body.release or not sum(s.duration for s in body.segments)
            ):
                raise ValueError(
                    'stage envelopes need positive duration and no release'
                )
            if isinstance(body, Envelope) and body.playback != PlaybackMode.once:
                if any(m.position in (0, 1) for m in body.markers):
                    raise ValueError('looping envelope markers must be interior')
                if any(m.name in ('turned', 'cycle') for m in body.markers):
                    raise ValueError('looping envelope marker names are reserved')
        for transition in self.transitions:
            if any(n not in names for n in transition.from_stages):
                raise ValueError('transition references an unknown source stage')
            if (
                isinstance(transition.action, EnterStage)
                and transition.action.stage not in names
            ):
                raise ValueError('transition references an unknown destination stage')
            if transition.event not in (
                'note_on',
                'note_off',
                'stage.done',
            ) and not transition.event.startswith(('cue.', 'stage.')):
                raise ValueError('transition event is unsupported')
            if transition.event.startswith('stage.'):
                port = transition.event.removeprefix('stage.')
                for name in transition.from_stages:
                    body = next(s.envelfo for s in self.stages if s.name == name)
                    ports = (
                        {m.name for m in body.markers}
                        if isinstance(body, (LFO, Envelope))
                        else set()
                    )
                    if (
                        not isinstance(body, Envelope)
                        or body.playback == PlaybackMode.once
                        or body.repeat_count is not None
                    ):
                        ports.add('done')
                    if isinstance(body, Envelope):
                        if body.playback != PlaybackMode.once:
                            ports.add('cycle')
                            if body.playback == PlaybackMode.ping_pong:
                                ports.add('turned')
                    if port not in ports:
                        raise ValueError(
                            'transition references an unknown stage marker'
                        )
        return self


def stage_event_ports(body: Stages) -> set[str]:
    ports = {'done', 'stage.done'} | {
        marker.name
        for stage in body.stages
        for marker in getattr(stage.envelfo, 'markers', [])
    }
    if any(
        isinstance(stage.envelfo, Envelope)
        and stage.envelfo.playback != PlaybackMode.once
        for stage in body.stages
    ):
        ports.add('cycle')
    if any(
        isinstance(stage.envelfo, Envelope)
        and stage.envelfo.playback == PlaybackMode.ping_pong
        for stage in body.stages
    ):
        ports.add('turned')
    return ports


class PatchEventConnection(Model):
    source: str = Field(min_length=3)
    target: Identifier
    action: Literal['start', 'cue', 'sample', 'capture'] = 'start'
    cue: Identifier | None = None
    every: int = Field(default=1, ge=1, strict=True)
    offset: int = Field(default=0, ge=0, strict=True)
    probability: UnitInterval = 1.0
    delay: Annotated[control.Rational, units.unit_validator('second', exact=True)] = (
        Field(default=Fraction(0), ge=0)
    )

    @model_validator(mode='after')
    def cue_payload(self) -> Self:
        if (self.action == 'cue') != (self.cue is not None):
            raise ValueError('only cue connections require a cue name')
        return self


class SampleHold(Model, frozen=True):
    kind: Literal['sample_hold'] = 'sample_hold'
    minimum: FiniteScalar = Field(default=-1.0, ge=-1, le=1)
    maximum: FiniteScalar = Field(default=1.0, ge=-1, le=1)

    @model_validator(mode='after')
    def output_range(self) -> Self:
        if self.minimum > self.maximum:
            raise ValueError('sample-and-hold minimum must not exceed maximum')
        return self


class Sum(Model, frozen=True):
    kind: Literal['sum'] = 'sum'
    inputs: list[Identifier] = Field(min_length=2)


class Product(Model, frozen=True):
    kind: Literal['product'] = 'product'
    inputs: list[Identifier] = Field(min_length=2)


class Affine(Model, frozen=True):
    kind: Literal['affine'] = 'affine'
    input: Identifier
    scale: FiniteScalar = 1.0
    offset: FiniteScalar = 0.0


class Latch(Model, frozen=True):
    kind: Literal['latch'] = 'latch'
    input: Identifier


class Quantize(Model, frozen=True):
    kind: Literal['quantize'] = 'quantize'
    input: Identifier
    step: FiniteScalar = Field(gt=0)
    origin: FiniteScalar = 0.0


def quantize_value(body: Quantize, value: float) -> float:
    """Round to the nearest grid point, choosing the higher point at a tie."""
    position = (value - body.origin) / body.step
    if not isfinite(position):
        raise ValueError('quantizer grid coordinate is not finite')
    lower = floor(position)
    return body.origin + (lower + (position - lower >= 0.5)) * body.step


class Threshold(Model, frozen=True):
    kind: Literal['threshold'] = 'threshold'
    input: Identifier
    lower: FiniteScalar
    upper: FiniteScalar

    @model_validator(mode='after')
    def hysteresis_window(self) -> Self:
        if self.lower >= self.upper:
            raise ValueError('threshold lower must be less than upper')
        return self


class Slew(Model, frozen=True):
    kind: Literal['slew'] = 'slew'
    input: Identifier
    rise: Annotated[FiniteScalar, units.unit_validator('1/second')] = Field(ge=0)
    fall: Annotated[FiniteScalar, units.unit_validator('1/second')] = Field(ge=0)
    initial: FiniteScalar | None = None


class Patch(Model):
    kind: Literal['patch'] = 'patch'
    envelfos: dict[
        Identifier,
        Annotated[
            LFO
            | Envelope
            | Stages
            | SampleHold
            | Sum
            | Product
            | Affine
            | Quantize
            | Latch
            | Threshold
            | Slew,
            Field(discriminator='kind'),
        ],
    ] = Field(min_length=1)
    outputs: dict[Identifier, Identifier] = Field(min_length=1)
    event_outputs: dict[Identifier, str] = Field(default_factory=dict)
    events: list[PatchEventConnection] = Field(default_factory=list)

    @cached_property
    def signal_order(self) -> list[str]:
        graph = {
            n: b.inputs
            if isinstance(b, (Sum, Product))
            else [b.input]
            if isinstance(b, (Affine, Quantize, Latch, Threshold, Slew))
            else []
            for n, b in self.envelfos.items()
        }
        if any(i not in graph for d in graph.values() for i in d):
            raise ValueError('patch signal input references an unknown child')
        try:
            return list(TopologicalSorter(graph).static_order())
        except CycleError:
            raise ValueError('patch signal dependencies contain a cycle') from None

    @cached_property
    def signal_ranges(self) -> dict[str, tuple[float, float]]:
        ranges: dict[str, tuple[float, float]] = {}
        for name in self.signal_order:
            body = self.envelfos[name]
            if isinstance(body, Sum):
                minimum, maximum = 0.0, 0.0
                for source in body.inputs:
                    lower, upper = ranges[source]
                    minimum += lower
                    maximum += upper
            elif isinstance(body, Product):
                minimum, maximum = 1.0, 1.0
                for source in body.inputs:
                    lower, upper = ranges[source]
                    values = [
                        minimum * lower,
                        minimum * upper,
                        maximum * lower,
                        maximum * upper,
                    ]
                    minimum, maximum = min(values), max(values)
            elif isinstance(body, Quantize):
                minimum, maximum = (quantize_value(body, v) for v in ranges[body.input])
            elif isinstance(body, Latch):
                minimum, maximum = ranges[body.input]
            elif isinstance(body, Threshold):
                minimum, maximum = 0.0, 1.0
            elif isinstance(body, Slew):
                minimum, maximum = ranges[body.input]
                if body.initial is not None:
                    minimum, maximum = (
                        min(minimum, body.initial),
                        max(maximum, body.initial),
                    )
            elif isinstance(body, Affine):
                values = [body.offset + body.scale * v for v in ranges[body.input]]
                minimum, maximum = min(values), max(values)
            else:
                minimum, maximum = (
                    (0.0, 1.0)
                    if isinstance(body, Envelope)
                    and body.polarity == control.Polarity.unipolar
                    else (-1.0, 1.0)
                )
            if not isfinite(minimum) or not isfinite(maximum):
                raise ValueError('patch signal range is not finite')
            ranges[name] = minimum, maximum
        return ranges

    @model_validator(mode='after')
    def selected_envelfos(self) -> Self:
        _ = self.signal_ranges
        if any(name not in self.envelfos for name in self.outputs.values()):
            raise ValueError('patch output references an unknown child Envelfo')
        for source in self.event_outputs.values():
            child, separator, port = source.partition('.')
            body = self.envelfos.get(child)
            if not separator or not port:
                raise ValueError('patch event output must name a child event')
            if isinstance(body, LFO):
                ports = {marker.name for marker in body.markers}
            elif isinstance(body, Stages):
                ports = stage_event_ports(body)
            elif isinstance(body, Threshold):
                ports = {'rising', 'falling'}
            else:
                ports = set()
            if port not in ports:
                raise ValueError('patch event output references an unknown child event')
        if any(
            isinstance(body, LFO) and isinstance(body.rate, ParameterReference)
            for body in self.envelfos.values()
        ):
            raise ValueError('patch LFO rates must be literals')
        if any(
            isinstance(body, Envelope) and body.initial == 'current'
            for body in self.envelfos.values()
        ):
            raise ValueError('patch envelopes need explicit initial values')
        for connection in self.events:
            source, separator, port = connection.source.partition('.')
            origin = self.envelfos.get(source)
            target = self.envelfos.get(connection.target)
            if not separator or not port:
                raise ValueError('patch event source must name a child event')
            if isinstance(origin, LFO):
                ports = {marker.name for marker in origin.markers}
            elif isinstance(origin, Stages):
                ports = stage_event_ports(origin)
            elif isinstance(origin, Threshold):
                ports = {'rising', 'falling'}
            else:
                raise ValueError('patch event source cannot emit this command')
            if port not in ports:
                raise ValueError(
                    'patch event source references an unknown '
                    + ('marker' if isinstance(origin, LFO) else 'stage event')
                )
            if connection.action == 'capture':
                if not isinstance(target, Latch):
                    raise ValueError('patch capture target must be a Latch')
            elif connection.action == 'sample':
                if not isinstance(target, SampleHold):
                    raise ValueError('patch sample target must be a SampleHold')
            elif connection.action == 'start':
                if (
                    not isinstance(target, Envelope)
                    or target.start != 'event'
                    or target.release
                    or target.playback != PlaybackMode.once
                    or target.retrigger != Retrigger.current
                ):
                    raise ValueError(
                        'patch start target must be an event-start Envelope'
                    )
            elif not isinstance(target, Stages) or not any(
                transition.event == f'cue.{connection.cue}'
                for transition in target.transitions
            ):
                raise ValueError('patch cue target has no matching stage transition')
        return self


class EnveLFO(Model):
    scope: control.Scope = control.Scope.voice
    clock: control.Clock = control.Clock.seconds
    position_driver: PositionDriver = PositionDriver.elapsed
    body: (
        Annotated[
            LFO | Envelope | Stages | SampleHold | Patch, Field(discriminator='kind')
        ]
        | None
    ) = None
    score: ScoreReference | None = None
    parameters: dict[Identifier, float | str] = Field(default_factory=dict)
    origin: EnvelfoOrigin | None = None

    @model_validator(mode='before')
    @classmethod
    def clock_units(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return dict(value) | {
            'body': _clock_body(
                value.get('body'), value.get('clock', control.Clock.seconds)
            )
        }

    @model_validator(mode='after')
    def one_definition(self) -> Self:
        if self.position_driver == PositionDriver.transport and (
            self.clock != control.Clock.beats
            or self.body is not None
            and (
                not isinstance(self.body, LFO)
                or self.body.reset != Reset.transport
                or self.body.delay != 0
                or self.body.fade_in != 0
            )
        ):
            raise ValueError(
                'transport position requires a beat-clock LFO with '
                'transport reset and no onset fade'
            )
        if (self.body is None) == (self.score is None):
            raise ValueError('EnveLFO requires exactly one body or score reference')
        if self.score is None and self.parameters:
            raise ValueError('inline envelfos do not accept public parameters')
        if self.score is not None and self.origin is not None:
            raise ValueError('unresolved envelfos cannot claim a materialized origin')
        if isinstance(self.body, LFO) and isinstance(
            self.body.rate, ParameterReference
        ):
            raise ValueError('inline LFO rate cannot reference a public parameter')
        if isinstance(self.body, Envelope) and self.body.initial == 'current':
            raise ValueError('current envelope initial requires a parent stage')
        if isinstance(self.body, SampleHold) and self.scope != control.Scope.voice:
            raise ValueError('sample-and-hold requires voice scope')
        if isinstance(self.body, Envelope) and any(
            s.duration_unit.value != self.clock.value
            for s in [*self.body.segments, *self.body.release]
        ):
            raise ValueError('envelope segment units must match its clock')
        if isinstance(self.body, Stages) and any(
            segment.duration_unit.value != self.clock.value
            for stage in self.body.stages
            if isinstance(stage.envelfo, Envelope)
            for segment in stage.envelfo.segments
        ):
            raise ValueError('stage envelope segment units must match its clock')
        if isinstance(self.body, Patch):
            if (
                any(isinstance(b, Latch) for b in self.body.envelfos.values())
                and self.scope != control.Scope.voice
            ):
                raise ValueError('latch requires voice scope')
            if (
                any(isinstance(b, Slew) for b in self.body.envelfos.values())
                and self.scope != control.Scope.voice
            ):
                raise ValueError('slew requires voice scope')
            if (
                any(isinstance(b, Threshold) for b in self.body.envelfos.values())
                and self.scope != control.Scope.voice
            ):
                raise ValueError('threshold requires voice scope')
            if (
                any(isinstance(b, SampleHold) for b in self.body.envelfos.values())
                and self.scope != control.Scope.voice
            ):
                raise ValueError('sample-and-hold requires voice scope')
            lfo_sources = {
                name
                for connection in self.body.events
                if isinstance(
                    self.body.envelfos[name := connection.source.partition('.')[0]],
                    LFO,
                )
            } | {
                source.partition('.')[0]
                for source in self.body.event_outputs.values()
                if isinstance(self.body.envelfos[source.partition('.')[0]], LFO)
            }
            if (self.body.events or lfo_sources) and self.scope != control.Scope.voice:
                raise ValueError('patch event connections require voice scope')
            if lfo_sources and self.clock != control.Clock.seconds:
                raise ValueError(
                    'patch marker connections require simple voice seconds LFOs'
                )
            for child_name in lfo_sources:
                child = self.body.envelfos[child_name]
                assert isinstance(child, LFO)
                if (
                    child.rate == 0
                    or child.reset != Reset.trigger
                    or child.delay
                    or child.fade_in
                ):
                    raise ValueError(
                        'patch marker connections require simple voice seconds LFOs'
                    )
            for child in self.body.envelfos.values():
                envelopes = (
                    [child]
                    if isinstance(child, Envelope)
                    else [
                        s.envelfo
                        for s in child.stages
                        if isinstance(s.envelfo, Envelope)
                    ]
                    if isinstance(child, Stages)
                    else []
                )
                if any(
                    segment.duration_unit.value != self.clock.value
                    for envelope in envelopes
                    for segment in [*envelope.segments, *envelope.release]
                ):
                    raise ValueError(
                        'patch envelope segment units must match its clock'
                    )
        return self


def _clock_body(value: object, clock: control.Clock | str) -> object:
    if isinstance(value, list):
        return [_clock_body(v, clock) for v in value]
    if not isinstance(value, dict):
        return value
    normalized = (
        control.clock_fields(value, clock) if value.get('kind') == 'lfo' else value
    )
    assert isinstance(normalized, dict)
    return {k: _clock_body(v, clock) for k, v in normalized.items()}


class EnvelfoEvent(control.ControlEvent):
    action: Literal[
        'start',
        'sample',
        'note_on',
        'note_off',
        'reset',
        'rate',
        'transport',
        'cue',
        'pause',
        'resume',
        'reverse',
        'seek',
        'shift',
    ]
    rate: control.Rational | None = Field(default=None, ge=0)
    cue: Identifier | None = None
    position: control.Rational | None = Field(default=None, ge=0, le=1)
    offset: control.Rational | None = None

    @model_validator(mode='after')
    def rate_payload(self) -> Self:
        if (self.action == 'rate') != (self.rate is not None):
            raise ValueError('only rate events require a rate')
        if (self.action == 'cue') != (self.cue is not None):
            raise ValueError('only cue events require a cue name')
        if (self.action == 'seek') != (self.position is not None):
            raise ValueError('only seek events require a position')
        if (self.action == 'shift') != (self.offset is not None):
            raise ValueError('only shift events require an offset')
        return self


class EnvelfoPosition(Model):
    at: control.Rational
    coordinate: control.Rational
    rate: control.Rational = Field(ge=0)
    direction: Literal[-1, 1] = 1
    paused: bool = False
    age: control.Rational = Field(default=Fraction(0), ge=0)


class LFOState(Model):
    at: control.Rational
    ordinal: int = -1
    position: EnvelfoPosition


class EnvelopeState(Model):
    at: control.Rational
    ordinal: int = -1
    phase: Literal['idle', 'on', 'release'] = 'idle'
    start_value: FiniteScalar
    position: EnvelfoPosition
    traversals: int = 0
    complete_coordinate: control.Rational | None = None


class StageState(Model):
    at: control.Rational
    ordinal: int = -1
    stage: Identifier
    entry_value: FiniteScalar
    position: EnvelfoPosition
    activation: int = 0
    cursor_order: int = -1
    completed: bool = False
    complete_value: FiniteScalar | None = None
    traversals: int = 0


class SampleHoldState(Model):
    at: control.Rational
    ordinal: int = -1
    value: FiniteScalar
    random_state: int = Field(ge=0, lt=2**64)


class EnvelfoState(Model):
    runtime: LFOState | EnvelopeState | StageState | SampleHoldState


class EnvelfoValue(Model):
    value: float
    weight: float
    status: Literal['idle', 'running', 'held', 'complete']


class EnvelfoOutputEvent(Model):
    at: control.Rational
    port: str
    stage: Identifier
    activation: int


class EnvelfoAdvance(Model):
    state: EnvelfoState
    value: EnvelfoValue
    events: list[EnvelfoOutputEvent] = Field(default_factory=list)


class EnvelfoScore(Score):
    kind: Literal['envelfo'] = 'envelfo'
    parameters: dict[Identifier, EnvelfoParameter] = Field(default_factory=dict)
    body: Annotated[
        LFO | Envelope | Stages | SampleHold | Patch, Field(discriminator='kind')
    ]

    @model_validator(mode='after')
    def public_parameters(self) -> Self:
        rate = self.body.rate if isinstance(self.body, LFO) else None
        used = {rate.parameter} if isinstance(rate, ParameterReference) else set()
        if used != self.parameters.keys():
            raise ValueError('envelfo parameters must each bind to a supported field')
        if (
            isinstance(rate, ParameterReference)
            and self.parameters[rate.parameter].unit != Unit.hz
        ):
            raise ValueError('LFO rate requires a Hz parameter')
        return self


def instantiate_envelfo(
    score: EnvelfoScore,
    parameters: dict[str, float | str] | None = None,
    scope: control.Scope = control.Scope.voice,
    clock: control.Clock = control.Clock.seconds,
    origin: EnvelfoOrigin | None = None,
    position_driver: PositionDriver = PositionDriver.elapsed,
) -> EnveLFO:
    values = parameters or {}
    if values.keys() - score.parameters.keys():
        raise ValueError('unknown public envelfo parameters')
    body = score.body
    if isinstance(body, LFO) and isinstance(body.rate, ParameterReference):
        declared = score.parameters[body.rate.parameter]
        value = unit_number(
            values.get(body.rate.parameter, declared.default), declared.unit
        )
        if not declared.minimum <= value <= declared.maximum:
            raise ValueError(
                f'envelfo parameter {body.rate.parameter} is outside its range'
            )
        body = LFO.model_validate(body.model_dump() | {'rate': Fraction(str(value))})
    return EnveLFO(
        scope=scope,
        clock=clock,
        position_driver=position_driver,
        body=body,
        origin=origin,
    )
