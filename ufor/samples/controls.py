"""Named expression domains, independent of any controller protocol."""

from fractions import Fraction
from typing import Self

from pydantic import Field, model_validator

from .. import control
from ..base import Bipolar, Model
from ..control import Polarity


class ControlDeclaration(Model):
    polarity: Polarity = Polarity.unipolar
    default: Bipolar = 0.0

    @model_validator(mode='after')
    def valid_default(self) -> Self:
        self.validate_value(self.default)
        return self

    def validate_value(self, value: float) -> None:
        minimum = -1.0 if self.polarity == Polarity.bipolar else 0.0
        if not minimum <= value <= 1.0:
            raise ValueError(f'{self.polarity} control value must be in [{minimum}, 1]')


class ControlValueEvent(control.ControlEvent):
    value: Bipolar


class ControlState(Model):
    """One source-domain ramp on the rational seconds clock."""

    at: control.Rational
    ordinal: int = Field(default=-1, ge=-1, strict=True)
    value: Bipolar
    target: Bipolar
    smoothing: control.Rational = Field(ge=0)


def initial_control(
    declaration: ControlDeclaration,
    at: Fraction,
    smoothing: Fraction,
    value: float | None = None,
) -> ControlState:
    initial = declaration.default if value is None else value
    declaration.validate_value(initial)
    return ControlState(at=at, value=initial, target=initial, smoothing=smoothing)


def control_at(state: ControlState, at: Fraction) -> float:
    elapsed = control.elapsed(at, state.at)
    if elapsed >= state.smoothing:
        return state.target
    return state.value + (state.target - state.value) * float(elapsed / state.smoothing)


def control_event(
    declaration: ControlDeclaration, state: ControlState, event: ControlValueEvent
) -> ControlState:
    control.check_order(state.at, state.ordinal, event)
    declaration.validate_value(event.value)
    return ControlState(
        at=event.at,
        ordinal=event.ordinal,
        value=control_at(state, event.at),
        target=event.value,
        smoothing=state.smoothing,
    )
