"""Semantic fixture cues, separate from physical DMX patching."""

from enum import StrEnum, auto
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


class ByteOrder(StrEnum):
    coarse_fine = auto()
    fine_coarse = auto()


class ChannelEncoding(Model):
    parameter: Identifier
    slots: list[int] = Field(min_length=1, max_length=2)
    minimum: float | None = None
    maximum: float | None = None
    values: dict[Identifier, int] = Field(default_factory=dict)
    byte_order: ByteOrder = ByteOrder.coarse_fine

    @model_validator(mode='after')
    def encoding_domain(self) -> Self:
        numeric = self.minimum is not None or self.maximum is not None
        if numeric == bool(self.values):
            raise ValueError('channel encoding needs numeric range or discrete values')
        if numeric and (
            self.minimum is None or self.maximum is None or self.minimum >= self.maximum
        ):
            raise ValueError('channel encoding range must increase')
        if len(self.slots) != len(set(self.slots)) or any(
            slot < 1 or slot > 512 for slot in self.slots
        ):
            raise ValueError('channel slots must be distinct DMX slots')
        if any(value < 0 or value > 255 for value in self.values.values()):
            raise ValueError('discrete DMX values must be bytes')
        return self


class CompositeRule(StrEnum):
    maximum = auto()
    override = auto()
    color_blend = auto()


class Compositor(Model):
    parameter: Identifier
    rule: CompositeRule


class StopBehavior(Model):
    kind: Literal['blackout', 'fade', 'hold']
    duration: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode='after')
    def fade_duration(self) -> Self:
        if (self.kind == 'fade') != (self.duration is not None):
            raise ValueError('only fades declare a duration')
        return self


class FixtureProfile(Model):
    name: Identifier
    parameters: list[FixtureParameter] = Field(min_length=1)
    channels: list[ChannelEncoding] = Field(default_factory=list)
    stop: StopBehavior = StopBehavior(kind='hold')

    @model_validator(mode='after')
    def distinct(self) -> Self:
        unique((p.name for p in self.parameters), 'fixture parameter')
        parameters = {p.name for p in self.parameters}
        unique((c.parameter for c in self.channels), 'encoded parameter')
        if any(c.parameter not in parameters for c in self.channels):
            raise ValueError('channel encoding references an unknown parameter')
        return self


class FixtureCue(Model):
    tick: int = Field(ge=0, strict=True)
    ordinal: int = Field(ge=0, strict=True)
    fixture: Identifier
    parameter: Identifier
    value: float | Identifier
    source: Identifier = 'score'


class FixturePatch(Model):
    fixture: Identifier
    universe: int = Field(ge=1, strict=True)
    universe_offset: int = -1
    start_slot: int = Field(ge=1, le=512, strict=True)

    @property
    def wire_universe(self) -> int:
        return self.universe + self.universe_offset


class RawDmxFrame(Model):
    tick: int = Field(ge=0, strict=True)
    universe: int = Field(ge=1, strict=True)
    slots: list[int] = Field(min_length=1, max_length=512)
    sequence: int | None = Field(default=None, ge=0, le=255, strict=True)

    @model_validator(mode='after')
    def bytes(self) -> Self:
        if any(slot < 0 or slot > 255 for slot in self.slots):
            raise ValueError('raw DMX slots must be bytes')
        return self


class RawDmxCapture(Model):
    patch_contract: Identifier
    frames: list[RawDmxFrame] = Field(min_length=1)
    synchronization: Literal['none', 'artnet_sync', 'scheduled'] = 'none'
    measured_skew_ticks: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode='after')
    def ordered(self) -> Self:
        if [frame.tick for frame in self.frames] != sorted(
            frame.tick for frame in self.frames
        ):
            raise ValueError('raw DMX frames must be ordered')
        if self.synchronization == 'none' and self.measured_skew_ticks is not None:
            raise ValueError('unsynchronized capture has no measured skew contract')
        return self


class PixelPatch(Model):
    light: Identifier
    device: Identifier
    index: int = Field(ge=0, strict=True)


class FixtureShow(Model):
    profile: FixtureProfile
    fixtures: list[Identifier] = Field(min_length=1)
    cues: list[FixtureCue] = Field(default_factory=list)
    compositors: list[Compositor] = Field(default_factory=list)
    raw_dmx: RawDmxCapture | None = None

    @model_validator(mode='after')
    def cue_contracts(self) -> Self:
        unique(self.fixtures, 'fixture')
        order = [(c.tick, c.ordinal) for c in self.cues]
        if order != sorted(order) or len({c.ordinal for c in self.cues}) != len(
            self.cues
        ):
            raise ValueError('fixture cues require ordered unique ordinals')
        parameters = {p.name: p for p in self.profile.parameters}
        unique((c.parameter for c in self.compositors), 'composited parameter')
        compositors = {c.parameter: c for c in self.compositors}
        if set(compositors) - set(parameters):
            raise ValueError('compositor references an unknown parameter')
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
        writers: set[tuple[int, Identifier, Identifier]] = set()
        for cue in self.cues:
            key = (cue.tick, cue.fixture, cue.parameter)
            if key in writers and cue.parameter not in compositors:
                raise ValueError('competing fixture writers require a compositor')
            writers.add(key)
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
