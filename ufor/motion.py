"""Portable definitions for reusable control motions."""

from enum import StrEnum, auto
from fractions import Fraction
from functools import cached_property
from graphlib import CycleError, TopologicalSorter
from math import ceil, floor, isfinite
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator
from reccy.configuration import units

from . import control, envelope, lfo, motion_random
from .base import FiniteScalar, Identifier, Model, UnitInterval, UnitScalar, unique
from .envelope import Retrigger
from .interface import ScoreReference
from .lfo import Reset
from .modulation import Unit, unit_fields, unit_number
from .oscillator import Waveform, shape_value
from .score import Score
from .segments import Segment


class ParameterReference(Model):
    parameter: Identifier


class MotionParameter(Model):
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
            raise ValueError('motion parameter has an invalid domain or default')
        if self.unit == Unit.hz and self.minimum == 0:
            raise ValueError('Hz motion parameters require a positive minimum')
        return self


class MotionOrigin(Model):
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


class Cycle(Model):
    kind: Literal['cycle'] = 'cycle'
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
            raise ValueError('cycle output must remain within [-1, 1]')
        if any(m.position == 1 for m in self.markers):
            raise ValueError('cycle marker positions must be less than one')
        unique((m.name for m in self.markers), 'cycle marker')
        return self

    @model_validator(mode='before')
    @classmethod
    def clock_units(cls, value: object) -> object:
        return control.clock_fields(value)


class Contour(Model):
    kind: Literal['contour'] = 'contour'
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
            raise ValueError('contour levels must be in [-1, 1]')
        if self.polarity == control.Polarity.unipolar and min(levels) < 0:
            raise ValueError('unipolar contour levels must be in [0, 1]')
        unique((m.name for m in self.markers), 'contour marker')
        if (self.loop_start is None) != (self.loop_end is None):
            raise ValueError('contour loop boundaries must be named together')
        if self.loop_start is not None:
            if self.playback == PlaybackMode.once:
                raise ValueError('once contours cannot name loop boundaries')
            positions = {m.name: m.position for m in self.markers}
            if self.loop_start not in positions or self.loop_end not in positions:
                raise ValueError('contour loop boundary marker is unknown')
            if positions[self.loop_start] >= positions[self.loop_end]:
                raise ValueError('contour loop start must precede its end')
            if any(m.position > positions[self.loop_end] for m in self.markers):
                raise ValueError('contour markers cannot follow its loop end')
        if self.repeat_count is not None and self.playback == PlaybackMode.once:
            raise ValueError('repeat count requires loop or ping-pong playback')
        return self


class Stage(Model):
    name: Identifier
    motion: Annotated[Hold | Cycle | Contour, Field(discriminator='kind')]


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
        initial = next(s.motion for s in self.stages if s.name == self.initial_stage)
        if isinstance(initial, Contour) and initial.initial == 'current':
            raise ValueError('initial stage cannot capture a current value')
        for stage in self.stages:
            body = stage.motion
            if isinstance(body, (Cycle, Contour)) and any(
                m.name == 'done' for m in body.markers
            ):
                raise ValueError('stage marker name done is reserved for completion')
            if isinstance(body, Cycle) and isinstance(body.rate, ParameterReference):
                raise ValueError('stage cycle rate must be a literal')
            if isinstance(body, Contour) and body.start == 'event':
                raise ValueError('stage contours start on stage entry')
            if isinstance(body, Contour) and (
                body.release or not sum(s.duration for s in body.segments)
            ):
                raise ValueError('stage contours need positive duration and no release')
            if isinstance(body, Contour) and body.playback != PlaybackMode.once:
                if any(m.position in (0, 1) for m in body.markers):
                    raise ValueError('looping contour markers must be interior')
                if any(m.name in ('turned', 'cycle') for m in body.markers):
                    raise ValueError('looping contour marker names are reserved')
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
                    body = next(s.motion for s in self.stages if s.name == name)
                    ports = (
                        {m.name for m in body.markers}
                        if isinstance(body, (Cycle, Contour))
                        else set()
                    )
                    if (
                        not isinstance(body, Contour)
                        or body.playback == PlaybackMode.once
                        or body.repeat_count is not None
                    ):
                        ports.add('done')
                    if isinstance(body, Contour):
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
        for marker in getattr(stage.motion, 'markers', [])
    }
    if any(
        isinstance(stage.motion, Contour) and stage.motion.playback != PlaybackMode.once
        for stage in body.stages
    ):
        ports.add('cycle')
    if any(
        isinstance(stage.motion, Contour)
        and stage.motion.playback == PlaybackMode.ping_pong
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


def latch_value(value: float, previous: float | None) -> float:
    """Capture on activation or when delivery has cleared the previous value."""
    return value if previous is None else previous


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


def slew_value(
    body: Slew, value: float, previous: float | None, seconds: Fraction
) -> float:
    """Limit one observation in signal units per second, without overshoot."""
    if previous is None:
        return value if body.initial is None else body.initial
    elapsed = float(seconds)
    if value >= previous:
        return min(value, previous + body.rise * elapsed)
    return max(value, previous - body.fall * elapsed)


def threshold_value(
    body: Threshold, value: float, previous: float | None
) -> tuple[float, str | None]:
    """Observe one grid sample; initialization is silent and deadband holds state."""
    output = float(value >= body.upper) if previous is None else previous
    if previous == 0 and value >= body.upper:
        return 1.0, 'rising'
    if previous == 1 and value <= body.lower:
        return 0.0, 'falling'
    return output, None


class Patch(Model):
    kind: Literal['patch'] = 'patch'
    motions: dict[
        Identifier,
        Annotated[
            Cycle
            | Contour
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
            for n, b in self.motions.items()
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
            body = self.motions[name]
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
                    if isinstance(body, Contour)
                    and body.polarity == control.Polarity.unipolar
                    else (-1.0, 1.0)
                )
            if not isfinite(minimum) or not isfinite(maximum):
                raise ValueError('patch signal range is not finite')
            ranges[name] = minimum, maximum
        return ranges

    @model_validator(mode='after')
    def selected_motions(self) -> Self:
        _ = self.signal_ranges
        if any(name not in self.motions for name in self.outputs.values()):
            raise ValueError('patch output references an unknown child Motion')
        for source in self.event_outputs.values():
            child, separator, port = source.partition('.')
            body = self.motions.get(child)
            if not separator or not port:
                raise ValueError('patch event output must name a child event')
            if isinstance(body, Cycle):
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
            isinstance(body, Cycle) and isinstance(body.rate, ParameterReference)
            for body in self.motions.values()
        ):
            raise ValueError('patch cycle rates must be literals')
        if any(
            isinstance(body, Contour) and body.initial == 'current'
            for body in self.motions.values()
        ):
            raise ValueError('patch contours need explicit initial values')
        for connection in self.events:
            source, separator, port = connection.source.partition('.')
            origin = self.motions.get(source)
            target = self.motions.get(connection.target)
            if not separator or not port:
                raise ValueError('patch event source must name a child event')
            if isinstance(origin, Cycle):
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
                    + ('marker' if isinstance(origin, Cycle) else 'stage event')
                )
            if connection.action == 'capture':
                if not isinstance(target, Latch):
                    raise ValueError('patch capture target must be a Latch')
            elif connection.action == 'sample':
                if not isinstance(target, SampleHold):
                    raise ValueError('patch sample target must be a SampleHold')
            elif connection.action == 'start':
                if (
                    not isinstance(target, Contour)
                    or target.start != 'event'
                    or target.release
                    or target.playback != PlaybackMode.once
                    or target.retrigger != Retrigger.current
                ):
                    raise ValueError(
                        'patch start target must be an event-start Contour'
                    )
            elif not isinstance(target, Stages) or not any(
                transition.event == f'cue.{connection.cue}'
                for transition in target.transitions
            ):
                raise ValueError('patch cue target has no matching stage transition')
        return self


def transform_value(
    body: Sum | Product | Affine | Quantize, signals: dict[str, float]
) -> float:
    if isinstance(body, Quantize):
        return quantize_value(body, signals[body.input])
    if isinstance(body, Affine):
        return body.offset + body.scale * signals[body.input]
    value = 0.0 if isinstance(body, Sum) else 1.0
    for name in body.inputs:
        if isinstance(body, Sum):
            value += signals[name]
        else:
            value *= signals[name]
    return value


class MotionUse(Model):
    scope: control.Scope = control.Scope.voice
    clock: control.Clock = control.Clock.seconds
    position_driver: PositionDriver = PositionDriver.elapsed
    body: (
        Annotated[
            Cycle | Contour | Stages | SampleHold | Patch, Field(discriminator='kind')
        ]
        | None
    ) = None
    score: ScoreReference | None = None
    parameters: dict[Identifier, float | str] = Field(default_factory=dict)
    origin: MotionOrigin | None = None

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
                not isinstance(self.body, Cycle)
                or self.body.reset != Reset.transport
                or self.body.delay != 0
                or self.body.fade_in != 0
            )
        ):
            raise ValueError(
                'transport position requires a beat-clock Cycle with '
                'transport reset and no onset fade'
            )
        if (self.body is None) == (self.score is None):
            raise ValueError('MotionUse requires exactly one body or score reference')
        if self.score is None and self.parameters:
            raise ValueError('inline motions do not accept public parameters')
        if self.score is not None and self.origin is not None:
            raise ValueError('unresolved motions cannot claim a materialized origin')
        if isinstance(self.body, Cycle) and isinstance(
            self.body.rate, ParameterReference
        ):
            raise ValueError('inline cycle rate cannot reference a public parameter')
        if isinstance(self.body, Contour) and self.body.initial == 'current':
            raise ValueError('current contour initial requires a parent stage')
        if isinstance(self.body, SampleHold) and self.scope != control.Scope.voice:
            raise ValueError('sample-and-hold requires voice scope')
        if isinstance(self.body, Contour) and any(
            s.duration_unit.value != self.clock.value
            for s in [*self.body.segments, *self.body.release]
        ):
            raise ValueError('contour segment units must match its clock')
        if isinstance(self.body, Stages) and any(
            segment.duration_unit.value != self.clock.value
            for stage in self.body.stages
            if isinstance(stage.motion, Contour)
            for segment in stage.motion.segments
        ):
            raise ValueError('stage contour segment units must match its clock')
        if isinstance(self.body, Patch):
            if (
                any(isinstance(b, Latch) for b in self.body.motions.values())
                and self.scope != control.Scope.voice
            ):
                raise ValueError('latch requires voice scope')
            if (
                any(isinstance(b, Slew) for b in self.body.motions.values())
                and self.scope != control.Scope.voice
            ):
                raise ValueError('slew requires voice scope')
            if (
                any(isinstance(b, Threshold) for b in self.body.motions.values())
                and self.scope != control.Scope.voice
            ):
                raise ValueError('threshold requires voice scope')
            if (
                any(isinstance(b, SampleHold) for b in self.body.motions.values())
                and self.scope != control.Scope.voice
            ):
                raise ValueError('sample-and-hold requires voice scope')
            cycle_sources = {
                name
                for connection in self.body.events
                if isinstance(
                    self.body.motions[name := connection.source.partition('.')[0]],
                    Cycle,
                )
            } | {
                source.partition('.')[0]
                for source in self.body.event_outputs.values()
                if isinstance(self.body.motions[source.partition('.')[0]], Cycle)
            }
            if (
                self.body.events or cycle_sources
            ) and self.scope != control.Scope.voice:
                raise ValueError('patch event connections require voice scope')
            if cycle_sources and self.clock != control.Clock.seconds:
                raise ValueError(
                    'patch marker connections require simple voice seconds Cycles'
                )
            for child_name in cycle_sources:
                child = self.body.motions[child_name]
                assert isinstance(child, Cycle)
                if (
                    child.rate == 0
                    or child.reset != Reset.trigger
                    or child.delay
                    or child.fade_in
                ):
                    raise ValueError(
                        'patch marker connections require simple voice seconds Cycles'
                    )
            for child in self.body.motions.values():
                contours = (
                    [child]
                    if isinstance(child, Contour)
                    else [
                        s.motion for s in child.stages if isinstance(s.motion, Contour)
                    ]
                    if isinstance(child, Stages)
                    else []
                )
                if any(
                    segment.duration_unit.value != self.clock.value
                    for contour in contours
                    for segment in [*contour.segments, *contour.release]
                ):
                    raise ValueError('patch contour segment units must match its clock')
        return self


def _clock_body(value: object, clock: control.Clock | str) -> object:
    if isinstance(value, list):
        return [_clock_body(v, clock) for v in value]
    if not isinstance(value, dict):
        return value
    normalized = (
        control.clock_fields(value, clock) if value.get('kind') == 'cycle' else value
    )
    assert isinstance(normalized, dict)
    return {k: _clock_body(v, clock) for k, v in normalized.items()}


class MotionEvent(control.ControlEvent):
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


class MotionPosition(Model):
    at: control.Rational
    coordinate: control.Rational
    rate: control.Rational = Field(ge=0)
    direction: Literal[-1, 1] = 1
    paused: bool = False
    age: control.Rational = Field(default=Fraction(0), ge=0)


class CycleState(Model):
    at: control.Rational
    ordinal: int = -1
    position: MotionPosition


class ContourState(Model):
    at: control.Rational
    ordinal: int = -1
    phase: Literal['idle', 'on', 'release'] = 'idle'
    start_value: FiniteScalar
    position: MotionPosition
    traversals: int = 0
    complete_coordinate: control.Rational | None = None


class StageState(Model):
    at: control.Rational
    ordinal: int = -1
    stage: Identifier
    entry_value: FiniteScalar
    position: MotionPosition
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


class MotionState(Model):
    runtime: CycleState | ContourState | StageState | SampleHoldState


class MotionValue(Model):
    value: float
    weight: float
    status: Literal['idle', 'running', 'held', 'complete']


class MotionOutputEvent(Model):
    at: control.Rational
    port: str
    stage: Identifier
    activation: int


class MotionAdvance(Model):
    state: MotionState
    value: MotionValue
    events: list[MotionOutputEvent] = Field(default_factory=list)


def cycle_lfo(motion: MotionUse) -> lfo.LFO:
    body = motion.body
    if not isinstance(body, Cycle):
        raise ValueError('motion is not a cycle')
    if isinstance(body.rate, ParameterReference):
        raise ValueError('cycle rate has an unresolved public parameter')
    return lfo.LFO(
        clock=motion.clock,
        scope=motion.scope,
        rate=body.rate,
        phase=body.phase,
        reset=body.reset,
        waveform=body.shape,
        duty_cycle=body.duty_cycle,
        delay=body.delay,
        fade_in=body.fade_in,
    )


def contour_envelope(motion: MotionUse) -> envelope.Envelope:
    body = motion.body
    if not isinstance(body, Contour):
        raise ValueError('motion is not a contour')
    if body.playback != PlaybackMode.once:
        raise ValueError('looping contours cannot be converted to envelopes')
    if body.initial == 'current':
        raise ValueError('contour current value needs stage entry')
    return envelope.Envelope(
        clock=motion.clock,
        scope=motion.scope,
        polarity=body.polarity,
        initial=body.initial,
        segments=body.segments,
        release=body.release
        or [Segment(duration=Fraction(0), to=body.segments[-1].to)],
        hold=body.hold if body.release else False,
        retrigger=body.retrigger,
    )


def _contour_rate(segments: list[Segment]) -> Fraction:
    duration = sum((s.duration for s in segments), Fraction(0))
    return Fraction(1, 1) / duration if duration else Fraction(0)


def _loop_bounds(body: Contour) -> tuple[Fraction, Fraction]:
    if body.loop_start is None or body.loop_end is None:
        return Fraction(0), Fraction(1)
    positions = {m.name: m.position for m in body.markers}
    return positions[body.loop_start], positions[body.loop_end]


def _contour_coordinate(
    coordinate: Fraction, body: Contour, release: bool = False
) -> Fraction:
    mode = PlaybackMode.once if release else body.playback
    start, end = _loop_bounds(body)
    if start or end != 1:
        if coordinate < end:
            return max(Fraction(0), coordinate)
        width = end - start
        if mode == PlaybackMode.loop:
            return start + (coordinate - end) % width
        if mode == PlaybackMode.ping_pong:
            position = (coordinate - end) % (2 * width)
            return end - position if position <= width else start + position - width
    if mode == PlaybackMode.loop:
        return coordinate % 1
    if mode == PlaybackMode.ping_pong:
        position = coordinate % 2
        return position if position <= 1 else 2 - position
    return max(Fraction(0), min(Fraction(1), coordinate))


def _repeat_crossings(
    body: Contour, position: MotionPosition, at: Fraction, remaining: int
) -> tuple[int, Fraction | None]:
    start, end = _loop_bounds(body)
    width = end - start
    coordinate = position.coordinate
    target = _coordinate_at(position, at)
    if position.paused or not position.rate or target == coordinate:
        return 0, None
    if position.direction == 1:
        first = (
            end + max(0, floor((coordinate - end) / width) + 1) * width
            if body.loop_start is not None
            else floor(coordinate) + 1
        )
        crossed = max(0, floor((target - first) / width) + 1)
        boundary = first + (remaining - 1) * width
    else:
        first = (
            end + (ceil((coordinate - end) / width) - 1) * width
            if body.loop_start is not None
            else ceil(coordinate) - 1
        )
        crossed = (
            max(0, floor((first - target) / width) + 1)
            if body.loop_start is None or first >= end
            else 0
        )
        boundary = first - (remaining - 1) * width
    return min(crossed, remaining), boundary if crossed >= remaining else None


def _repeat_boundary_coordinate(
    body: Contour, boundary: Fraction, direction: int
) -> Fraction:
    if body.playback == PlaybackMode.loop:
        start, end = _loop_bounds(body)
        return end if direction == 1 else start
    return _contour_coordinate(boundary, body)


def _initial_position(body: Hold | Cycle | Contour, at: Fraction) -> MotionPosition:
    if isinstance(body, Cycle):
        assert isinstance(body.rate, Fraction)
        return MotionPosition(at=at, coordinate=body.phase, rate=body.rate)
    if isinstance(body, Contour):
        return MotionPosition(
            at=at, coordinate=Fraction(0), rate=_contour_rate(body.segments)
        )
    return MotionPosition(at=at, coordinate=Fraction(0), rate=Fraction(0))


def _coordinate_at(position: MotionPosition, at: Fraction) -> Fraction:
    elapsed = control.elapsed(at, position.at)
    if position.paused:
        return position.coordinate
    return position.coordinate + position.direction * position.rate * elapsed


def _age_at(position: MotionPosition, at: Fraction) -> Fraction:
    elapsed = control.elapsed(at, position.at)
    return position.age if position.paused else position.age + elapsed


def _position_at(position: MotionPosition, at: Fraction) -> MotionPosition:
    return position.model_copy(
        update={
            'at': at,
            'coordinate': _coordinate_at(position, at),
            'age': _age_at(position, at),
        }
    )


def _position_command(position: MotionPosition, event: MotionEvent) -> MotionPosition:
    if event.action == 'pause':
        return position.model_copy(update={'paused': True})
    if event.action == 'resume':
        return position.model_copy(update={'paused': False})
    if event.action == 'reverse':
        return position.model_copy(update={'direction': -position.direction})
    if event.action == 'seek':
        assert event.position is not None
        return position.model_copy(update={'coordinate': event.position})
    if event.action == 'shift':
        assert event.offset is not None
        return position.model_copy(
            update={'coordinate': position.coordinate + event.offset}
        )
    if event.action == 'rate':
        assert event.rate is not None
        return position.model_copy(update={'rate': event.rate})
    return position


def _contour_value(body: Contour, state: ContourState, at: Fraction) -> MotionValue:
    if state.phase == 'idle':
        assert isinstance(body.initial, float)
        return MotionValue(value=body.initial, weight=1, status='idle')
    segments = body.release if state.phase == 'release' else body.segments
    duration = sum((s.duration for s in segments), Fraction(0))
    complete_coordinate = state.complete_coordinate
    if (
        complete_coordinate is None
        and state.phase == 'on'
        and body.repeat_count is not None
    ):
        _, boundary = _repeat_crossings(
            body, state.position, at, body.repeat_count - state.traversals
        )
        if boundary is not None:
            complete_coordinate = _repeat_boundary_coordinate(
                body, boundary, state.position.direction
            )
    coordinate = (
        complete_coordinate
        if complete_coordinate is not None
        else _contour_coordinate(
            _coordinate_at(state.position, at), body, state.phase != 'on'
        )
        if duration
        else Fraction(1)
    )
    value = envelope.curve_at(
        envelope.Curve(initial=state.start_value, segments=segments),
        coordinate * duration,
    )
    if complete_coordinate is not None:
        status = 'complete'
    elif state.phase == 'on' and body.playback != PlaybackMode.once:
        status = 'running'
    elif coordinate < 1:
        status = 'running'
    elif state.phase == 'on' and body.hold and body.release:
        status = 'held'
    else:
        status = 'complete'
    return MotionValue(value=value, weight=1, status=status)


def initial_motion(motion: MotionUse, at: Fraction, *, seed: int = 0) -> MotionState:
    if isinstance(motion.body, SampleHold):
        random_state, word = motion_random.random_word(seed)
        return MotionState(
            runtime=SampleHoldState(
                at=at,
                value=motion.body.minimum
                + (motion.body.maximum - motion.body.minimum) * ((word >> 11) / 2**53),
                random_state=random_state,
            )
        )
    if isinstance(motion.body, Cycle):
        assert isinstance(motion.body.rate, Fraction)
        return MotionState(
            runtime=CycleState(
                at=at,
                position=MotionPosition(
                    at=at, coordinate=motion.body.phase, rate=motion.body.rate
                ),
            )
        )
    if isinstance(motion.body, Stages):
        stage = next(
            s for s in motion.body.stages if s.name == motion.body.initial_stage
        )
        initial = stage.motion.initial if isinstance(stage.motion, Contour) else 0.0
        assert isinstance(initial, float)
        return MotionState(
            runtime=StageState(
                at=at,
                stage=stage.name,
                entry_value=initial,
                position=_initial_position(stage.motion, at),
            )
        )
    if not isinstance(motion.body, Contour):
        raise ValueError('motion reference must be materialized before use')
    assert isinstance(motion.body.initial, float)
    return MotionState(
        runtime=ContourState(
            at=at,
            phase=(
                'idle' if motion.body.release or motion.body.start == 'event' else 'on'
            ),
            start_value=motion.body.initial,
            position=_initial_position(motion.body, at).model_copy(
                update={
                    'coordinate': Fraction(1)
                    if not sum(s.duration for s in motion.body.segments)
                    else Fraction(0)
                }
            ),
        )
    )


def motion_at(motion: MotionUse, state: MotionState, at: Fraction) -> MotionValue:
    if isinstance(motion.body, SampleHold) and isinstance(
        state.runtime, SampleHoldState
    ):
        if at < state.runtime.at:
            raise ValueError('sample-and-hold observation precedes its state')
        return MotionValue(value=state.runtime.value, weight=1.0, status='held')
    if isinstance(motion.body, Cycle) and isinstance(state.runtime, CycleState):
        position = state.runtime.position
        if motion.position_driver == PositionDriver.transport:
            assert isinstance(motion.body.rate, Fraction)
            return MotionValue(
                value=motion.body.center
                + motion.body.depth
                * shape_value(
                    motion.body.shape,
                    (motion.body.phase + motion.body.rate * at) % 1,
                    motion.body.duty_cycle,
                ),
                weight=1.0,
                status='running',
            )
        coordinate = _coordinate_at(position, at)
        age = _age_at(position, at)
        if age < motion.body.delay:
            weight = 0.0
        elif motion.body.fade_in:
            weight = float(
                min(Fraction(1), (age - motion.body.delay) / motion.body.fade_in)
            )
        else:
            weight = 1.0
        return MotionValue(
            value=motion.body.center
            + motion.body.depth
            * shape_value(motion.body.shape, coordinate % 1, motion.body.duty_cycle),
            weight=weight,
            status='running',
        )
    if isinstance(motion.body, Stages) and isinstance(state.runtime, StageState):
        return advance_motion(motion, state, at).value
    if isinstance(motion.body, Contour) and isinstance(state.runtime, ContourState):
        return _contour_value(motion.body, state.runtime, at)
    raise ValueError('motion state does not match its definition')


def motion_event(
    motion: MotionUse, state: MotionState, event: MotionEvent
) -> MotionState:
    if isinstance(motion.body, SampleHold) and isinstance(
        state.runtime, SampleHoldState
    ):
        control.check_order(state.runtime.at, state.runtime.ordinal, event)
        if event.action not in (
            'sample',
            'note_on',
            'note_off',
            'pause',
            'resume',
            'seek',
            'shift',
            'reverse',
        ):
            raise ValueError('sample-and-hold does not accept this event')
        runtime = state.runtime
        if event.action == 'sample':
            random_state, word = motion_random.random_word(runtime.random_state)
            runtime = runtime.model_copy(
                update={
                    'value': motion.body.minimum
                    + (motion.body.maximum - motion.body.minimum)
                    * ((word >> 11) / 2**53),
                    'random_state': random_state,
                }
            )
        return MotionState(
            runtime=runtime.model_copy(
                update={'at': event.at, 'ordinal': event.ordinal}
            )
        )
    if motion.position_driver == PositionDriver.transport:
        raise ValueError('transport-position Cycle does not accept phase commands')
    if isinstance(motion.body, Stages) and isinstance(state.runtime, StageState):
        return advance_motion(motion, state, event.at, event).state
    if isinstance(motion.body, Cycle) and isinstance(state.runtime, CycleState):
        if event.action == 'cue':
            raise ValueError('cycles do not accept cue events')
        if event.action == 'sample':
            raise ValueError('cycles do not accept sample events')
        control.check_order(state.runtime.at, state.runtime.ordinal, event)
        position = _position_at(state.runtime.position, event.at)
        if event.action in ('note_on', 'reset', 'transport'):
            if (
                event.action == 'reset'
                or (event.action == 'note_on' and motion.body.reset == Reset.trigger)
                or (
                    event.action == 'transport' and motion.body.reset == Reset.transport
                )
            ):
                position = position.model_copy(
                    update={'coordinate': motion.body.phase, 'age': Fraction(0)}
                )
        else:
            position = _position_command(position, event)
        return MotionState(
            runtime=CycleState(at=event.at, ordinal=event.ordinal, position=position)
        )
    if isinstance(motion.body, Contour) and isinstance(state.runtime, ContourState):
        if event.action in ('cue', 'reset', 'transport', 'rate', 'sample'):
            raise ValueError('contours do not accept this event')
        control.check_order(state.runtime.at, state.runtime.ordinal, event)
        runtime = state.runtime
        position = _position_at(runtime.position, event.at)
        phase = runtime.phase
        start_value = runtime.start_value
        traversals = runtime.traversals
        complete_coordinate = runtime.complete_coordinate
        if (
            phase == 'on'
            and complete_coordinate is None
            and motion.body.repeat_count is not None
        ):
            crossed, boundary = _repeat_crossings(
                motion.body,
                runtime.position,
                event.at,
                motion.body.repeat_count - traversals,
            )
            traversals += crossed
            if boundary is not None:
                position = position.model_copy(update={'coordinate': boundary})
                complete_coordinate = _repeat_boundary_coordinate(
                    motion.body, boundary, runtime.position.direction
                )
        observed = _contour_value(motion.body, runtime, event.at)
        if event.action == 'start' or (
            event.action == 'note_on' and motion.body.start == 'activation'
        ):
            active = observed.status in ('running', 'held')
            if not active or motion.body.retrigger != Retrigger.ignore:
                assert isinstance(motion.body.initial, float)
                start_value = (
                    observed.value
                    if motion.body.retrigger == Retrigger.current
                    else motion.body.initial
                )
                phase = 'on'
                traversals = 0
                complete_coordinate = None
                position = position.model_copy(
                    update={
                        'coordinate': Fraction(0),
                        'age': Fraction(0),
                        'rate': _contour_rate(motion.body.segments),
                    }
                )
        elif event.action == 'note_off':
            if motion.body.release and phase == 'on' and observed.status != 'complete':
                phase = 'release'
                start_value = observed.value
                position = position.model_copy(
                    update={
                        'coordinate': Fraction(0),
                        'age': Fraction(0),
                        'rate': _contour_rate(motion.body.release),
                    }
                )
        else:
            position = _position_command(position, event)
            if event.action == 'shift' and (
                phase == 'release' or motion.body.playback == PlaybackMode.once
            ):
                position = position.model_copy(
                    update={
                        'coordinate': max(
                            Fraction(0), min(Fraction(1), position.coordinate)
                        )
                    }
                )
        return MotionState(
            runtime=ContourState(
                at=event.at,
                ordinal=event.ordinal,
                phase=phase,
                start_value=start_value,
                position=position,
                traversals=traversals,
                complete_coordinate=complete_coordinate,
            )
        )
    raise ValueError('motion state does not match its definition')


def advance_motion(
    motion: MotionUse,
    state: MotionState,
    at: Fraction,
    event: MotionEvent | None = None,
) -> MotionAdvance:
    """Advance a staged Motion, returning its state and ordered output events."""
    body = motion.body
    runtime = state.runtime
    if not isinstance(body, Stages) or not isinstance(runtime, StageState):
        raise ValueError('advance_motion requires staged Motion state')
    control.elapsed(at, runtime.at)
    if event is not None:
        if event.at != at:
            raise ValueError('Motion event time must equal the advance boundary')
        control.check_order(runtime.at, runtime.ordinal, event)
    current, emitted = _advance_stages(body, runtime, at, event is None)
    if event is not None:
        if event.action in ('pause', 'resume', 'reverse', 'seek', 'shift', 'rate'):
            stage = next(s.motion for s in body.stages if s.name == current.stage)
            if event.action in ('seek', 'shift') and isinstance(stage, Hold):
                raise ValueError('hold stages do not accept position events')
            position = _position_command(_position_at(current.position, at), event)
            if (
                event.action == 'shift'
                and isinstance(stage, Contour)
                and stage.playback == PlaybackMode.once
            ):
                position = position.model_copy(
                    update={
                        'coordinate': max(
                            Fraction(0), min(Fraction(1), position.coordinate)
                        )
                    }
                )
            current = current.model_copy(
                update={
                    'position': position,
                    'cursor_order': -1,
                }
            )
        else:
            key = f'cue.{event.cue}' if event.action == 'cue' else event.action
            activation = current.activation
            current, output = _stage_transition(body, current, at, key)
            emitted.extend(output)
            if current.activation == activation and not current.completed:
                current, output = _advance_stages(body, current, at, True)
                emitted.extend(output)
        current = current.model_copy(
            update={
                'at': at,
                'ordinal': event.ordinal,
                'cursor_order': current.cursor_order,
            }
        )
    value = _stage_value(body, current, at)
    return MotionAdvance(
        state=MotionState(runtime=current), value=value, events=emitted
    )


def _advance_stages(
    body: Stages, state: StageState, at: Fraction, inclusive: bool
) -> tuple[StageState, list[MotionOutputEvent]]:
    emitted: list[MotionOutputEvent] = []
    while (natural := _next_stage_event(body, state, at, inclusive)) is not None:
        time, order, port = natural
        stage = state.stage
        activation = state.activation
        state = state.model_copy(
            update={
                'at': time,
                'ordinal': state.ordinal if state.at == time else -1,
                'cursor_order': order,
                'position': _position_at(state.position, time),
            }
        )
        contour = next(s.motion for s in body.stages if s.name == stage)
        if (
            isinstance(contour, Contour)
            and contour.repeat_count is not None
            and port == ('cycle' if contour.playback == PlaybackMode.loop else 'turned')
        ):
            state = state.model_copy(update={'traversals': state.traversals + 1})
        final_repeat = (
            isinstance(contour, Contour)
            and contour.repeat_count is not None
            and state.traversals == contour.repeat_count
            and port == ('cycle' if contour.playback == PlaybackMode.loop else 'turned')
        )
        emitted.append(
            MotionOutputEvent(
                at=time,
                port='stage.done' if port == 'done' else port,
                stage=stage,
                activation=activation,
            )
        )
        if final_repeat:
            assert isinstance(contour, Contour)
            start, end = _loop_bounds(contour)
            if (
                contour.playback == PlaybackMode.ping_pong
                and (state.position.coordinate - end) / (end - start) % 2 == 1
            ):
                emitted.append(
                    MotionOutputEvent(
                        at=time, port='cycle', stage=stage, activation=activation
                    )
                )
            emitted.append(
                MotionOutputEvent(
                    at=time, port='stage.done', stage=stage, activation=activation
                )
            )
        state, output = _stage_transition(body, state, time, f'stage.{port}')
        emitted.extend(output)
        if final_repeat and state.stage == stage and state.activation == activation:
            state, output = _stage_transition(body, state, time, 'stage.done')
            emitted.extend(output)
            if state.stage == stage and state.activation == activation:
                value = _stage_value(body, state, time).value
                state = state.model_copy(
                    update={'completed': True, 'complete_value': value}
                )
        if len(emitted) > 4096:
            raise ValueError('Motion event capacity exceeded')
    if inclusive:
        state = state.model_copy(
            update={
                'at': at,
                'ordinal': state.ordinal if state.at == at else -1,
                'cursor_order': -1 if state.at != at else state.cursor_order,
                'position': _position_at(state.position, at),
            }
        )
    return state, emitted


def _next_stage_event(
    body: Stages, state: StageState, limit: Fraction, inclusive: bool
) -> tuple[Fraction, int, str] | None:
    if state.completed:
        return None
    stage = next(s.motion for s in body.stages if s.name == state.stage)
    if isinstance(stage, Hold):
        return None
    candidates: list[tuple[Fraction, int, str]] = []
    position = state.position
    if position.paused or not position.rate:
        return None
    start = position.coordinate
    forward = position.direction == 1
    if isinstance(stage, Contour):
        if stage.playback == PlaybackMode.once:
            for index, marker in enumerate(stage.markers):
                target = marker.position
                if (target > start if forward else target < start) or (
                    target == start
                    and state.cursor_order >= 0
                    and (
                        index > state.cursor_order
                        if forward
                        else index < state.cursor_order
                    )
                ):
                    time = state.at + abs(target - start) / position.rate
                    candidates.append((time, index, marker.name))
            if forward and (
                start < 1
                or (start == 1 and 0 <= state.cursor_order < len(stage.markers))
            ):
                candidates.append(
                    (state.at + (1 - start) / position.rate, len(stage.markers), 'done')
                )
        elif stage.loop_start is not None:
            candidates.extend(_named_loop_candidates(stage, state))
        else:
            period = 1 if stage.playback == PlaybackMode.loop else 2
            for index, marker in enumerate(stage.markers):
                offsets = (
                    [marker.position]
                    if period == 1
                    else [marker.position, 2 - marker.position]
                )
                for offset in offsets:
                    turn = (
                        floor((start - offset) / period) + 1
                        if forward
                        else ceil((start - offset) / period) - 1
                    )
                    target = turn * period + offset
                    candidates.append(
                        (
                            state.at + abs(target - start) / position.rate,
                            index,
                            marker.name,
                        )
                    )
                    if (
                        state.cursor_order >= 0
                        and (start - offset) % period == 0
                        and (
                            index > state.cursor_order
                            if forward
                            else index < state.cursor_order
                        )
                    ):
                        candidates.append((state.at, index, marker.name))
            boundary = floor(start) + 1 if forward else ceil(start) - 1
            order = len(stage.markers)
            candidates.append(
                (
                    state.at + abs(boundary - start) / position.rate,
                    order,
                    'cycle' if period == 1 else 'turned',
                )
            )
            if period == 2 and boundary % 2 == 0:
                candidates.append(
                    (
                        state.at + abs(boundary - start) / position.rate,
                        order + 1,
                        'cycle',
                    )
                )
            if period == 2 and start.denominator == 1 and start % 2 == 0:
                if state.cursor_order == order:
                    candidates.append((state.at, order + 1, 'cycle'))
    else:
        assert isinstance(stage, Cycle)
        for index, marker in enumerate(stage.markers):
            offset = start - marker.position
            turn = floor(offset) + 1 if forward else ceil(offset) - 1
            target = turn + marker.position
            time = state.at + abs(target - start) / position.rate
            candidates.append((time, index, marker.name))
            if (
                state.cursor_order >= 0
                and offset.denominator == 1
                and (
                    index > state.cursor_order
                    if forward
                    else index < state.cursor_order
                )
            ):
                candidates.append((state.at, index, marker.name))
    available = [
        c for c in candidates if (c[0] <= limit if inclusive else c[0] < limit)
    ]
    if not available:
        return None
    return (
        min(available)
        if forward
        else min(
            available,
            key=lambda c: (
                c[0],
                c[1] if c[2] in ('turned', 'cycle') else -c[1],
            ),
        )
    )


def _named_loop_candidates(
    stage: Contour, state: StageState
) -> list[tuple[Fraction, int, str]]:
    start, end = _loop_bounds(stage)
    width = end - start
    position = state.position
    coordinate = position.coordinate
    forward = position.direction == 1
    period = width if stage.playback == PlaybackMode.loop else 2 * width
    candidates: list[tuple[Fraction, int, str]] = []

    def add(target: Fraction, order: int, port: str) -> None:
        if (target > coordinate if forward else target < coordinate) or (
            target == coordinate
            and state.cursor_order >= 0
            and (
                order > state.cursor_order
                if forward
                else (
                    state.cursor_order < len(stage.markers)
                    and (order < state.cursor_order or order == len(stage.markers))
                )
            )
        ):
            candidates.append(
                (state.at + abs(target - coordinate) / position.rate, order, port)
            )

    def repeat(base: Fraction, order: int, port: str) -> None:
        turn = (
            max(0, floor((coordinate - base) / period) + 1)
            if forward
            else ceil((coordinate - base) / period) - 1
        )
        if turn >= 0:
            add(base + turn * period, order, port)
        if coordinate >= base and (coordinate - base) % period == 0:
            add(coordinate, order, port)

    for order, marker in enumerate(stage.markers):
        add(marker.position, order, marker.name)
        if marker.position < start:
            continue
        if stage.playback == PlaybackMode.loop:
            base = end + (marker.position - start)
            repeat(base, order, marker.name)
        else:
            if marker.position < end:
                repeat(end + end - marker.position, order, marker.name)
            if marker.position > start:
                repeat(end + width + marker.position - start, order, marker.name)

    order = len(stage.markers)
    boundary = (
        max(0, floor((coordinate - end) / width) + 1)
        if forward
        else ceil((coordinate - end) / width) - 1
    )
    if boundary >= 0:
        target = end + boundary * width
        add(target, order, 'cycle' if stage.playback == PlaybackMode.loop else 'turned')
        if stage.playback == PlaybackMode.ping_pong and boundary % 2 == 1:
            add(target, order + 1, 'cycle')
    if coordinate >= end and (coordinate - end) % width == 0:
        boundary = int((coordinate - end) / width)
        add(
            coordinate,
            order,
            'cycle' if stage.playback == PlaybackMode.loop else 'turned',
        )
        if stage.playback == PlaybackMode.ping_pong and boundary % 2 == 1:
            if state.cursor_order == order:
                candidates.append((state.at, order + 1, 'cycle'))
    return candidates


def _stage_transition(
    body: Stages, state: StageState, at: Fraction, event: str
) -> tuple[StageState, list[MotionOutputEvent]]:
    if state.completed:
        return state, []
    transition = next(
        (
            t
            for t in body.transitions
            if state.stage in t.from_stages and t.event == event
        ),
        None,
    )
    if transition is None:
        return state, []
    value = _stage_value(body, state, at).value
    if isinstance(transition.action, EnterStage):
        target = next(
            s.motion for s in body.stages if s.name == transition.action.stage
        )
        entry = (
            value
            if isinstance(target, Contour) and target.initial == 'current'
            else target.initial
            if isinstance(target, Contour)
            else value
        )
        assert isinstance(entry, float)
        return (
            StageState(
                at=at,
                ordinal=state.ordinal,
                stage=transition.action.stage,
                entry_value=entry,
                position=_initial_position(target, at).model_copy(
                    update={
                        'paused': state.position.paused,
                        'direction': state.position.direction,
                    }
                ),
                activation=state.activation + 1,
            ),
            [],
        )
    return (
        state.model_copy(update={'at': at, 'completed': True, 'complete_value': value}),
        [
            MotionOutputEvent(
                at=at, port='done', stage=state.stage, activation=state.activation
            )
        ],
    )


def _stage_value(body: Stages, state: StageState, at: Fraction) -> MotionValue:
    if state.completed:
        assert state.complete_value is not None
        return MotionValue(value=state.complete_value, weight=1, status='complete')
    stage = next(s.motion for s in body.stages if s.name == state.stage)
    if isinstance(stage, Hold):
        return MotionValue(value=stage.value, weight=1, status='held')
    position = state.position
    coordinate = _coordinate_at(position, at)
    if isinstance(stage, Cycle):
        phase = coordinate % 1
        age = _age_at(position, at)
        if age < stage.delay:
            weight = 0.0
        elif stage.fade_in:
            weight = float(min(Fraction(1), (age - stage.delay) / stage.fade_in))
        else:
            weight = 1.0
        value = stage.center + stage.depth * weight * shape_value(
            stage.shape, phase, stage.duty_cycle
        )
        return MotionValue(value=value, weight=1, status='running')
    curve = envelope.Curve(initial=state.entry_value, segments=stage.segments)
    duration = sum((s.duration for s in stage.segments), Fraction(0))
    bounded = _contour_coordinate(coordinate, stage)
    complete = stage.repeat_count is not None and state.traversals >= stage.repeat_count
    if complete:
        bounded = _repeat_boundary_coordinate(stage, coordinate, position.direction)
    value = envelope.curve_at(curve, bounded * duration)
    return MotionValue(
        value=value,
        weight=1,
        status='complete'
        if complete
        else 'running'
        if stage.playback != PlaybackMode.once or bounded < 1
        else 'held',
    )


class MotionScore(Score):
    kind: Literal['motion'] = 'motion'
    parameters: dict[Identifier, MotionParameter] = Field(default_factory=dict)
    body: Annotated[
        Cycle | Contour | Stages | SampleHold | Patch, Field(discriminator='kind')
    ]

    @model_validator(mode='after')
    def public_parameters(self) -> Self:
        rate = self.body.rate if isinstance(self.body, Cycle) else None
        used = {rate.parameter} if isinstance(rate, ParameterReference) else set()
        if used != self.parameters.keys():
            raise ValueError('motion parameters must each bind to a supported field')
        if (
            isinstance(rate, ParameterReference)
            and self.parameters[rate.parameter].unit != Unit.hz
        ):
            raise ValueError('cycle rate requires a Hz parameter')
        return self


def instantiate_motion(
    score: MotionScore,
    parameters: dict[str, float | str] | None = None,
    scope: control.Scope = control.Scope.voice,
    clock: control.Clock = control.Clock.seconds,
    origin: MotionOrigin | None = None,
    position_driver: PositionDriver = PositionDriver.elapsed,
) -> MotionUse:
    values = parameters or {}
    if values.keys() - score.parameters.keys():
        raise ValueError('unknown public motion parameters')
    body = score.body
    if isinstance(body, Cycle) and isinstance(body.rate, ParameterReference):
        declared = score.parameters[body.rate.parameter]
        value = unit_number(
            values.get(body.rate.parameter, declared.default), declared.unit
        )
        if not declared.minimum <= value <= declared.maximum:
            raise ValueError(
                f'motion parameter {body.rate.parameter} is outside its range'
            )
        body = Cycle.model_validate(body.model_dump() | {'rate': Fraction(str(value))})
    return MotionUse(
        scope=scope,
        clock=clock,
        position_driver=position_driver,
        body=body,
        origin=origin,
    )
