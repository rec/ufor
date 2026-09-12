"""Semantic fixture cues, separate from physical DMX patching."""

from typing import Literal, Self

from pydantic import Field, model_validator

from .base import Identifier, Model, unique
from .modulation import Unit
from .score import Score
from .time import Timebase


class FixtureParameter(Model):
    name: Identifier
    unit: Unit | None = None
    minimum: float | None = None
    maximum: float | None = None
    choices: list[Identifier] = Field(default_factory=list)

    @model_validator(mode='after')
    def domain(self) -> Self:
        numeric = self.minimum is not None or self.maximum is not None
        if numeric == bool(self.choices) or (
            numeric
            and (
                self.minimum is None
                or self.maximum is None
                or self.minimum >= self.maximum
            )
        ):
            raise ValueError(
                'fixture parameter needs one valid numeric or discrete domain'
            )
        if numeric and self.unit is None:
            raise ValueError('numeric fixture parameter requires a unit')
        unique(self.choices, 'fixture choice')
        return self


class FixtureProfile(Model):
    name: Identifier
    parameters: list[FixtureParameter] = Field(min_length=1)

    @model_validator(mode='after')
    def distinct(self) -> Self:
        unique((p.name for p in self.parameters), 'fixture parameter')
        return self


class FixtureCue(Model):
    tick: int = Field(ge=0, strict=True)
    ordinal: int = Field(ge=0, strict=True)
    fixture: Identifier
    parameter: Identifier
    value: float | Identifier


class FixturePatch(Model):
    fixture: Identifier
    universe: int = Field(ge=1, strict=True)
    universe_offset: int = -1
    start_slot: int = Field(ge=1, le=512, strict=True)

    @property
    def wire_universe(self) -> int:
        return self.universe + self.universe_offset


class FixtureShow(Model):
    profile: FixtureProfile
    fixtures: list[Identifier] = Field(min_length=1)
    cues: list[FixtureCue] = Field(default_factory=list)

    @model_validator(mode='after')
    def cue_contracts(self) -> Self:
        unique(self.fixtures, 'fixture')
        order = [(c.tick, c.ordinal) for c in self.cues]
        if order != sorted(order) or len({c.ordinal for c in self.cues}) != len(
            self.cues
        ):
            raise ValueError('fixture cues require ordered unique ordinals')
        parameters = {p.name: p for p in self.profile.parameters}
        for cue in self.cues:
            if cue.fixture not in self.fixtures or cue.parameter not in parameters:
                raise ValueError(
                    'fixture cue references an unknown fixture or parameter'
                )
            parameter = parameters[cue.parameter]
            if parameter.choices:
                if cue.value not in parameter.choices:
                    raise ValueError('fixture cue has an unsupported discrete value')
            elif (
                isinstance(cue.value, str)
                or parameter.minimum is None
                or parameter.maximum is None
                or not parameter.minimum <= cue.value <= parameter.maximum
            ):
                raise ValueError('fixture cue is outside its numeric domain')
        return self


class FixtureScore(Score):
    kind: Literal['fixture'] = 'fixture'
    timebase: Timebase
    body: FixtureShow


def patch_fixtures(
    show: FixtureShow, patches: list[FixturePatch]
) -> dict[str, FixturePatch]:
    """Validate a repatch without changing a fixture cue or sending DMX."""
    unique((p.fixture for p in patches), 'patched fixture')
    result = {p.fixture: p for p in patches}
    if set(result) != set(show.fixtures):
        raise ValueError('every logical fixture requires one physical patch')
    if any(p.wire_universe < 0 for p in patches):
        raise ValueError('patch creates a negative Art-Net wire universe')
    return result
