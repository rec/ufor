"""Exact LFO phase and scalar controls, without audio buffer generation."""

from enum import StrEnum, auto
from fractions import Fraction
from math import pi, sin
from typing import Literal, Self

from pydantic import Field, model_validator

from . import control
from .base import Model
from .document import Document
from .oscillator import Waveform


class Reset(StrEnum):
    free = auto()
    trigger = auto()
    transport = auto()


class LFO(Model):
    clock: control.Clock = control.Clock.seconds
    scope: control.Scope = control.Scope.voice
    rate: control.Rational = Field(ge=0)
    phase: control.Rational = Field(default=Fraction(0), ge=0, lt=1)
    reset: Reset = Reset.trigger
    waveform: Waveform = Waveform.sine
    duty_cycle: control.Rational = Field(default=Fraction(1, 2), ge=0, le=1)
    delay: control.Rational = Field(default=Fraction(0), ge=0)
    fade_in: control.Rational = Field(default=Fraction(0), ge=0)


class LFODocument(Document):
    kind: Literal['lfo'] = 'lfo'
    body: LFO


class LFOEvent(control.ControlEvent):
    action: Literal['trigger', 'transport', 'reset', 'rate']
    rate: control.Rational | None = Field(default=None, ge=0)

    @model_validator(mode='after')
    def rate_payload(self) -> Self:
        if (self.action == 'rate') != (self.rate is not None):
            raise ValueError('only rate events require a rate')
        return self


class LFOState(Model):
    at: control.Rational
    ordinal: int = -1
    started_at: control.Rational
    phase: control.Rational = Field(ge=0, lt=1)
    rate: control.Rational = Field(ge=0)


class LFOValue(Model):
    phase: control.Rational
    value: float
    weight: float


def initial_lfo(lfo: LFO, at: Fraction) -> LFOState:
    return LFOState(at=at, started_at=at, phase=lfo.phase, rate=lfo.rate)


def phase_at(state: LFOState, at: Fraction) -> Fraction:
    return (state.phase + state.rate * control.elapsed(at, state.at)) % 1


def lfo_at(lfo: LFO, state: LFOState, at: Fraction) -> LFOValue:
    phase = phase_at(state, at)
    age = control.elapsed(at, state.started_at)
    if age < lfo.delay:
        weight = 0.0
    elif lfo.fade_in:
        weight = float(min(Fraction(1), (age - lfo.delay) / lfo.fade_in))
    else:
        weight = 1.0
    return LFOValue(
        phase=phase,
        value=shape_value(lfo.waveform, phase, lfo.duty_cycle),
        weight=weight,
    )


def lfo_event(lfo: LFO, state: LFOState, event: LFOEvent) -> LFOState:
    control.check_order(state.at, state.ordinal, event)
    phase = phase_at(state, event.at)
    start = state.started_at
    rate = state.rate if event.rate is None else event.rate
    if event.action == 'reset' or event.action == lfo.reset.value:
        start, phase = event.at, lfo.phase
    return LFOState(
        at=event.at, ordinal=event.ordinal, started_at=start, phase=phase, rate=rate
    )


def shape_value(waveform: Waveform, phase: Fraction, duty_cycle: Fraction) -> float:
    """Single control observation using Tuney's documented shape equations."""
    if not 0 <= phase < 1 or not 0 <= duty_cycle <= 1:
        raise ValueError('shape requires phase in [0, 1) and duty in [0, 1]')
    if waveform == Waveform.sine:
        return sin(2 * pi * float(phase))
    if waveform == Waveform.square:
        return 1.0 if phase < duty_cycle else -1.0
    if phase < duty_cycle:
        return float(2 * phase / duty_cycle - 1)
    return float((1 + duty_cycle - 2 * phase) / (1 - duty_cycle))
