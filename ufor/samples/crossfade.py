"""Layer selection fades, independent of processing parameter routes."""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, model_validator

from ..base import Identifier, Model, Number, Seconds
from . import enums


class Crossfade(Model):
    input: enums.Input
    direction: enums.FadeDirection
    start: StrictInt | Number
    end: StrictInt | Number
    curve: enums.FadeCurve = enums.FadeCurve.linear

    @model_validator(mode='after')
    def valid_interval(self) -> Self:
        validate_input_value(self.input, self.start)
        validate_input_value(self.input, self.end)
        if self.start >= self.end:
            raise ValueError('Crossfade start must precede end')
        return self


class KeyCrossfade(Crossfade):
    input: Literal[enums.Input.key, enums.Input.velocity]


class ControlCrossfade(Crossfade):
    input: Literal[enums.Input.control]
    control: Identifier

    scope: Literal['part', 'instrument', 'trigger'] = 'part'

    smoothing_seconds: Seconds = 0.005


def validate_input_value(source: enums.Input, value: int | float) -> None:
    if source == enums.Input.key:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError('Key input points must be integers')
        return
    low, high = (-1, 1) if source == enums.Input.control else (0, 1)
    if not low <= value <= high:
        raise ValueError(f'{source} input must be in [{low}, {high}]')


LayerCrossfade = Annotated[
    KeyCrossfade | ControlCrossfade, Field(discriminator='input')
]
