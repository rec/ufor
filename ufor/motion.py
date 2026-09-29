"""Portable definitions for reusable control motions."""

from fractions import Fraction
from math import floor
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from . import control, envelope, lfo
from .base import FiniteScalar, Identifier, Model, unique
from .envelope import Retrigger
from .interface import ScoreReference
from .lfo import Reset
from .modulation import Unit
from .oscillator import Waveform, shape_value
from .score import Score
from .segments import Segment


class ParameterReference(Model):
    parameter: Identifier


class MotionParameter(Model):
    unit: Unit
    default: float
    minimum: float
    maximum: float
    description: str | None = None

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


class Cycle(Model):
    kind: Literal['cycle'] = 'cycle'
    shape: Waveform = Waveform.sine
    rate: ParameterReference | Annotated[control.Rational, Field(ge=0)]
    phase: control.Rational = Field(default=Fraction(0), ge=0, lt=1)
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

    @field_validator('rate', mode='before')
    @classmethod
    def hertz_rate(cls, value: object) -> object:
        if isinstance(value, str) and value.endswith(' Hz'):
            return value.removesuffix(' Hz')
        return value


class Contour(Model):
    kind: Literal['contour'] = 'contour'
    initial: FiniteScalar | Literal['current'] = 0.0
    segments: list[Segment] = Field(min_length=1)
    release: list[Segment] = Field(default_factory=list)
    polarity: control.Polarity = control.Polarity.unipolar
    hold: bool = True
    retrigger: Retrigger = Retrigger.current
    markers: list[Marker] = Field(default_factory=list)

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
            if isinstance(body, Cycle) and isinstance(body.rate, ParameterReference):
                raise ValueError('stage cycle rate must be a literal')
            if isinstance(body, Contour) and (
                body.release or not sum(s.duration for s in body.segments)
            ):
                raise ValueError('stage contours need positive duration and no release')
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
            if (
                transition.event.startswith('stage.')
                and transition.event != 'stage.done'
            ):
                port = transition.event.removeprefix('stage.')
                for name in transition.from_stages:
                    body = next(s.motion for s in self.stages if s.name == name)
                    if not isinstance(body, (Cycle, Contour)) or port not in {
                        m.name for m in body.markers
                    }:
                        raise ValueError(
                            'transition references an unknown stage marker'
                        )
        return self


class MotionUse(Model):
    scope: control.Scope = control.Scope.voice
    clock: control.Clock = control.Clock.seconds
    body: Annotated[Cycle | Contour | Stages, Field(discriminator='kind')] | None = None
    score: ScoreReference | None = None
    parameters: dict[Identifier, float] = Field(default_factory=dict)
    origin: MotionOrigin | None = None

    @model_validator(mode='after')
    def one_definition(self) -> Self:
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
        return self


class MotionEvent(control.ControlEvent):
    action: Literal['note_on', 'note_off', 'reset', 'rate', 'transport', 'cue']
    rate: control.Rational | None = Field(default=None, ge=0)
    cue: Identifier | None = None

    @model_validator(mode='after')
    def rate_payload(self) -> Self:
        if (self.action == 'rate') != (self.rate is not None):
            raise ValueError('only rate events require a rate')
        if (self.action == 'cue') != (self.cue is not None):
            raise ValueError('only cue events require a cue name')
        return self


class StageState(Model):
    at: control.Rational
    ordinal: int = -1
    stage: Identifier
    entered_at: control.Rational
    entry_value: FiniteScalar
    activation: int = 0
    cursor_order: int = -1
    completed: bool = False
    complete_value: FiniteScalar | None = None


class MotionState(Model):
    runtime: lfo.LFOState | envelope.EnvelopeState | StageState


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


def initial_motion(motion: MotionUse, at: Fraction) -> MotionState:
    if isinstance(motion.body, Cycle):
        return MotionState(runtime=lfo.initial_lfo(cycle_lfo(motion), at))
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
                entered_at=at,
                entry_value=initial,
            )
        )
    if not isinstance(motion.body, Contour):
        raise ValueError('motion reference must be materialized before use')
    state = envelope.initial_envelope(contour_envelope(motion), at)
    if not motion.body.release:
        state = state.model_copy(update={'phase': 'on'})
    return MotionState(runtime=state)


def motion_at(motion: MotionUse, state: MotionState, at: Fraction) -> MotionValue:
    if isinstance(motion.body, Cycle) and isinstance(state.runtime, lfo.LFOState):
        value = lfo.lfo_at(cycle_lfo(motion), state.runtime, at)
        return MotionValue(
            value=motion.body.center + motion.body.depth * value.value,
            weight=value.weight,
            status='running',
        )
    if isinstance(motion.body, Stages) and isinstance(state.runtime, StageState):
        return advance_motion(motion, state, at).value
    if isinstance(motion.body, Contour) and isinstance(
        state.runtime, envelope.EnvelopeState
    ):
        value = envelope.envelope_at(contour_envelope(motion), state.runtime, at)
        return MotionValue(value=value.value, weight=1, status=value.status)
    raise ValueError('motion state does not match its definition')


def motion_event(
    motion: MotionUse, state: MotionState, event: MotionEvent
) -> MotionState:
    if isinstance(motion.body, Stages) and isinstance(state.runtime, StageState):
        return advance_motion(motion, state, event.at, event).state
    if isinstance(motion.body, Cycle) and isinstance(state.runtime, lfo.LFOState):
        if event.action == 'cue':
            raise ValueError('cycles do not accept cue events')
        if event.action in ('note_off', 'note_on'):
            action = 'trigger'
            if event.action == 'note_off':
                control.check_order(state.runtime.at, state.runtime.ordinal, event)
                return MotionState(
                    runtime=state.runtime.model_copy(
                        update={
                            'at': event.at,
                            'ordinal': event.ordinal,
                            'phase': lfo.phase_at(state.runtime, event.at),
                        }
                    )
                )
        else:
            action = event.action
        return MotionState(
            runtime=lfo.lfo_event(
                cycle_lfo(motion),
                state.runtime,
                lfo.LFOEvent(
                    at=event.at, ordinal=event.ordinal, action=action, rate=event.rate
                ),
            )
        )
    if isinstance(motion.body, Contour) and isinstance(
        state.runtime, envelope.EnvelopeState
    ):
        if event.action not in ('note_on', 'note_off'):
            raise ValueError('contours accept only note events')
        if event.action == 'note_off' and not motion.body.release:
            control.check_order(state.runtime.at, state.runtime.ordinal, event)
            return MotionState(
                runtime=state.runtime.model_copy(
                    update={'at': event.at, 'ordinal': event.ordinal}
                )
            )
        return MotionState(
            runtime=envelope.envelope_event(
                contour_envelope(motion),
                state.runtime,
                envelope.EnvelopeEvent(
                    at=event.at,
                    ordinal=event.ordinal,
                    action='trigger' if event.action == 'note_on' else 'release',
                ),
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
            }
        )
        emitted.append(
            MotionOutputEvent(
                at=time,
                port='stage.done' if port == 'done' else port,
                stage=stage,
                activation=activation,
            )
        )
        state, output = _stage_transition(body, state, time, f'stage.{port}')
        emitted.extend(output)
        if len(emitted) > 4096:
            raise ValueError('Motion event capacity exceeded')
    if inclusive:
        state = state.model_copy(
            update={
                'at': at,
                'ordinal': state.ordinal if state.at == at else -1,
                'cursor_order': -1 if state.at != at else state.cursor_order,
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
    if isinstance(stage, Contour):
        duration = sum((s.duration for s in stage.segments), Fraction(0))
        for index, marker in enumerate(stage.markers):
            candidates.append(
                (state.entered_at + duration * marker.position, index, marker.name)
            )
        candidates.append((state.entered_at + duration, len(stage.markers), 'done'))
    else:
        assert isinstance(stage, Cycle)
        assert isinstance(stage.rate, Fraction)
        if stage.rate:
            for index, marker in enumerate(stage.markers):
                turn = floor(
                    (state.at - state.entered_at) * stage.rate
                    + stage.phase
                    - marker.position
                )
                for count in (turn, turn + 1):
                    time = (
                        state.entered_at
                        + (count + marker.position - stage.phase) / stage.rate
                    )
                    if time >= state.entered_at:
                        candidates.append((time, index, marker.name))
    available = [
        c
        for c in candidates
        if c[0] > state.entered_at
        and (c[0], c[1]) > (state.at, state.cursor_order)
        and (c[0] <= limit if inclusive else c[0] < limit)
    ]
    return min(available) if available else None


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
                entered_at=at,
                entry_value=entry,
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
    elapsed = control.elapsed(at, state.entered_at)
    if isinstance(stage, Cycle):
        assert isinstance(stage.rate, Fraction)
        phase = (stage.phase + stage.rate * elapsed) % 1
        if elapsed < stage.delay:
            weight = 0.0
        elif stage.fade_in:
            weight = float(min(Fraction(1), (elapsed - stage.delay) / stage.fade_in))
        else:
            weight = 1.0
        value = stage.center + stage.depth * weight * shape_value(
            stage.shape, phase, stage.duty_cycle
        )
        return MotionValue(value=value, weight=1, status='running')
    curve = envelope.Curve(initial=state.entry_value, segments=stage.segments)
    value = envelope.curve_at(curve, elapsed)
    duration = sum((s.duration for s in stage.segments), Fraction(0))
    return MotionValue(
        value=value, weight=1, status='running' if elapsed < duration else 'held'
    )


class MotionScore(Score):
    kind: Literal['motion'] = 'motion'
    parameters: dict[Identifier, MotionParameter] = Field(default_factory=dict)
    body: Annotated[Cycle | Contour | Stages, Field(discriminator='kind')]

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
    parameters: dict[str, float] | None = None,
    scope: control.Scope = control.Scope.voice,
    clock: control.Clock = control.Clock.seconds,
    origin: MotionOrigin | None = None,
) -> MotionUse:
    values = parameters or {}
    if values.keys() - score.parameters.keys():
        raise ValueError('unknown public motion parameters')
    body = score.body
    if isinstance(body, Cycle) and isinstance(body.rate, ParameterReference):
        declared = score.parameters[body.rate.parameter]
        value = values.get(body.rate.parameter, declared.default)
        if not declared.minimum <= value <= declared.maximum:
            raise ValueError(
                f'motion parameter {body.rate.parameter} is outside its range'
            )
        body = Cycle.model_validate(body.model_dump() | {'rate': Fraction(str(value))})
    return MotionUse(scope=scope, clock=clock, body=body, origin=origin)
