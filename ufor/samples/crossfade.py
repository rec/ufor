"""Layer selection fades, independent of processing parameter routes."""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, model_validator

from ..base import FiniteScalar, Identifier, Model, Seconds
from . import enums


class Crossfade(Model):
    input: enums.CrossfadeInput
    direction: enums.FadeDirection
    start: StrictInt | FiniteScalar
    end: StrictInt | FiniteScalar
    curve: enums.FadeCurve = enums.FadeCurve.linear

    @model_validator(mode='after')
    def valid_interval(self) -> Self:
        validate_input_value(self.input, self.start)
        validate_input_value(self.input, self.end)
        if self.start >= self.end:
            raise ValueError('Crossfade start must precede end')
        return self


class KeyCrossfade(Crossfade):
    input: Literal[enums.CrossfadeInput.key, enums.CrossfadeInput.velocity]


class ControlCrossfade(Crossfade):
    input: Literal[enums.CrossfadeInput.control]
    control: Identifier

    scope: Literal['part', 'instrument', 'trigger'] = 'part'

    smoothing_seconds: Seconds = 0.005


def validate_input_value(source: enums.CrossfadeInput, value: int | float) -> None:
    if source == enums.CrossfadeInput.key:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError('NoteKey input points must be integers')
        return
    low, high = (-1, 1) if source == enums.CrossfadeInput.control else (0, 1)
    if not low <= value <= high:
        raise ValueError(f'{source} input must be in [{low}, {high}]')


LayerCrossfade = Annotated[
    KeyCrossfade | ControlCrossfade, Field(discriminator='input')
]
