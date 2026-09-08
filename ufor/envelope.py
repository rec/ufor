"""Segmented control envelopes and pure event/state reference calculations."""

from enum import StrEnum, auto
from fractions import Fraction
from math import exp, expm1
from typing import Literal, Self

from pydantic import Field, model_validator

from . import control
from .base import Model
from .document import Document


class Retrigger(StrEnum):
    reset = auto()
    current = auto()
    ignore = auto()


class Segment(Model):
    duration: control.Rational = Field(ge=0)
    target: float = Field(ge=-1, le=1)
    curve: float = 0


class Envelope(Model):
    clock: control.Clock = control.Clock.seconds
    scope: control.Scope = control.Scope.voice
    polarity: control.Polarity = control.Polarity.unipolar
    initial: float = Field(default=0, ge=-1, le=1)
    segments: list[Segment] = Field(min_length=1)
    release: list[Segment] = Field(min_length=1)
    hold: bool = True
    retrigger: Retrigger = Retrigger.current

    @model_validator(mode='after')
    def levels_match_polarity(self) -> Self:
        if (
            self.polarity == control.Polarity.unipolar
            and min(self.initial, *(s.target for s in [*self.segments, *self.release]))
            < 0
        ):
            raise ValueError('unipolar envelope levels must be in [0, 1]')
        return self


class EnvelopeDocument(Document):
    kind: Literal['envelope'] = 'envelope'
    body: Envelope


class EnvelopeEvent(control.ControlEvent):
    action: Literal['trigger', 'release']


class EnvelopeState(Model):
    at: control.Rational
    ordinal: int = -1
    started_at: control.Rational
    start_value: float
    phase: Literal['idle', 'on', 'release'] = 'idle'


class EnvelopeValue(Model):
    value: float
    status: Literal['idle', 'running', 'held', 'complete']
    segment: int | None = None


def initial_envelope(envelope: Envelope, at: Fraction) -> EnvelopeState:
    return EnvelopeState(at=at, started_at=at, start_value=envelope.initial)


def envelope_at(
    envelope: Envelope, state: EnvelopeState, at: Fraction
) -> EnvelopeValue:
    control.elapsed(at, state.at)
    if state.phase == 'idle':
        return EnvelopeValue(value=envelope.initial, status='idle')
    remaining = control.elapsed(at, state.started_at)
    value = state.start_value
    segments = envelope.release if state.phase == 'release' else envelope.segments
    for index, segment in enumerate(segments):
        if remaining < segment.duration:
            progress = float(remaining / segment.duration)
            value += (segment.target - value) * curve_progress(progress, segment.curve)
            return EnvelopeValue(value=value, status='running', segment=index)
        remaining -= segment.duration
        value = segment.target
    status = 'held' if state.phase == 'on' and envelope.hold else 'complete'
    return EnvelopeValue(value=value, status=status)


def envelope_event(
    envelope: Envelope, state: EnvelopeState, event: EnvelopeEvent
) -> EnvelopeState:
    control.check_order(state.at, state.ordinal, event)
    observation = envelope_at(envelope, state, event.at)
    start = state.started_at
    value = state.start_value
    phase = state.phase
    if event.action == 'trigger':
        active = observation.status in ('running', 'held')
        if not active or envelope.retrigger != Retrigger.ignore:
            start = event.at
            value = (
                observation.value
                if envelope.retrigger == Retrigger.current
                else envelope.initial
            )
            phase = 'on'
    elif state.phase == 'on' and observation.status != 'complete':
        start, value, phase = event.at, observation.value, 'release'
    return EnvelopeState(
        at=event.at,
        ordinal=event.ordinal,
        started_at=start,
        start_value=value,
        phase=phase,
    )


def curve_progress(progress: float, curve: float) -> float:
    """Normalized exponential, stable for either sign and exact at endpoints."""
    if not 0 <= progress <= 1:
        raise ValueError('segment progress must be in [0, 1]')
    if progress in (0, 1) or curve == 0:
        return progress
    if curve > 0:
        return exp(curve * (progress - 1)) * expm1(-curve * progress) / expm1(-curve)
    return expm1(curve * progress) / expm1(curve)
