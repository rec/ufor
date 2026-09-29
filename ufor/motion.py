"""Portable definitions for reusable control motions."""

from fractions import Fraction
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from . import control, envelope, lfo
from .base import FiniteScalar, Model
from .envelope import Retrigger
from .lfo import Reset
from .oscillator import Waveform
from .score import Score
from .segments import Segment


class Cycle(Model):
    kind: Literal['cycle'] = 'cycle'
    shape: Waveform = Waveform.sine
    rate: control.Rational = Field(ge=0)
    phase: control.Rational = Field(default=Fraction(0), ge=0, lt=1)
    duty_cycle: control.Rational = Field(default=Fraction(1, 2), ge=0, le=1)
    reset: Reset = Reset.trigger
    delay: control.Rational = Field(default=Fraction(0), ge=0)
    fade_in: control.Rational = Field(default=Fraction(0), ge=0)

    @field_validator('rate', mode='before')
    @classmethod
    def hertz_rate(cls, value: object) -> object:
        if isinstance(value, str) and value.endswith(' Hz'):
            return value.removesuffix(' Hz')
        return value


class Contour(Model):
    kind: Literal['contour'] = 'contour'
    initial: FiniteScalar = 0.0
    segments: list[Segment] = Field(min_length=1)
    release: list[Segment] = Field(default_factory=list)
    polarity: control.Polarity = control.Polarity.unipolar
    hold: bool = True
    retrigger: Retrigger = Retrigger.current

    @model_validator(mode='after')
    def levels_match_polarity(self) -> Self:
        levels = [self.initial, *(s.to for s in [*self.segments, *self.release])]
        if any(not -1 <= value <= 1 for value in levels):
            raise ValueError('contour levels must be in [-1, 1]')
        if self.polarity == control.Polarity.unipolar and min(levels) < 0:
            raise ValueError('unipolar contour levels must be in [0, 1]')
        return self


class MotionUse(Model):
    scope: control.Scope = control.Scope.voice
    clock: control.Clock = control.Clock.seconds
    body: Annotated[Cycle | Contour, Field(discriminator='kind')]


class MotionEvent(control.ControlEvent):
    action: Literal['note_on', 'note_off', 'reset', 'rate', 'transport']
    rate: control.Rational | None = Field(default=None, ge=0)

    @model_validator(mode='after')
    def rate_payload(self) -> Self:
        if (self.action == 'rate') != (self.rate is not None):
            raise ValueError('only rate events require a rate')
        return self


class MotionState(Model):
    runtime: lfo.LFOState | envelope.EnvelopeState


class MotionValue(Model):
    value: float
    weight: float
    status: Literal['idle', 'running', 'held', 'complete']


def cycle_lfo(motion: MotionUse) -> lfo.LFO:
    body = motion.body
    if not isinstance(body, Cycle):
        raise ValueError('motion is not a cycle')
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
    state = envelope.initial_envelope(contour_envelope(motion), at)
    if not motion.body.release:
        state = state.model_copy(update={'phase': 'on'})
    return MotionState(runtime=state)


def motion_at(motion: MotionUse, state: MotionState, at: Fraction) -> MotionValue:
    if isinstance(motion.body, Cycle) and isinstance(state.runtime, lfo.LFOState):
        value = lfo.lfo_at(cycle_lfo(motion), state.runtime, at)
        return MotionValue(value=value.value, weight=value.weight, status='running')
    if isinstance(motion.body, Contour) and isinstance(
        state.runtime, envelope.EnvelopeState
    ):
        value = envelope.envelope_at(contour_envelope(motion), state.runtime, at)
        return MotionValue(value=value.value, weight=1, status=value.status)
    raise ValueError('motion state does not match its definition')


def motion_event(
    motion: MotionUse, state: MotionState, event: MotionEvent
) -> MotionState:
    if isinstance(motion.body, Cycle) and isinstance(state.runtime, lfo.LFOState):
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


class MotionScore(Score):
    kind: Literal['motion'] = 'motion'
    body: Annotated[Cycle | Contour, Field(discriminator='kind')]
