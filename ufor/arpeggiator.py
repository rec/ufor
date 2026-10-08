"""Portable arpeggiator profiles, independent of MIDI and audio devices."""

from fractions import Fraction
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from .base import Model
from .control import Rational
from .score import Score
from .selector import parse_selector


class HeldBank(Model):
    kind: Literal['held'] = 'held'


class LatchedBank(Model):
    kind: Literal['latched'] = 'latched'
    update: Literal['replace', 'add', 'toggle'] = 'replace'


class HistoryBank(Model):
    kind: Literal['history'] = 'history'
    notes: int = Field(default=8, strict=True, ge=1)
    publish: Literal['step'] = 'step'


class PhraseBank(Model, frozen=True):
    kind: Literal['phrase'] = 'phrase'
    publish: Literal['step'] = 'step'


class RegionsBank(Model):
    kind: Literal['regions'] = 'regions'
    reference: str

    @field_validator('reference')
    @classmethod
    def canonical_reference(cls, value: str) -> str:
        return str(parse_selector(value))


class Ascending(Model):
    kind: Literal['ascending'] = 'ascending'
    key: Literal['pitch', 'selection_key'] = 'pitch'
    repeats: int = Field(default=1, strict=True, ge=1)


class Descending(Model):
    kind: Literal['descending'] = 'descending'
    key: Literal['pitch', 'selection_key'] = 'pitch'


class Played(Model):
    kind: Literal['played'] = 'played'
    direction: Literal['forward', 'reverse'] = 'forward'


class Alternating(Model, frozen=True):
    kind: Literal['alternating'] = 'alternating'
    repeat_endpoints: bool = Field(default=False, strict=True)


class InsideOut(Model, frozen=True):
    kind: Literal['inside_out'] = 'inside_out'


class OutsideIn(Model, frozen=True):
    kind: Literal['outside_in'] = 'outside_in'


class IndexPattern(Model, frozen=True):
    kind: Literal['index_pattern'] = 'index_pattern'
    indices: list[Annotated[int, Field(strict=True, ge=0)]] = Field(min_length=1)
    boundary: Literal['wrap', 'rest'] = 'wrap'


class Shuffle(Model, frozen=True):
    kind: Literal['shuffle'] = 'shuffle'
    mode: Literal['once', 'cycle'] = 'cycle'
    no_repeat: bool = Field(default=False, strict=True)
    on_edit: Literal['restart', 'preserve'] = 'restart'


class Choice(Model, frozen=True):
    kind: Literal['choice'] = 'choice'
    weights: list[Annotated[int, Field(strict=True, ge=1, le=2**32 - 1)]] = Field(
        default=[1], min_length=1
    )
    extend: Literal['ones', 'repeat'] = 'ones'
    no_repeat: bool = Field(default=False, strict=True)


class Walk(Model):
    kind: Literal['walk'] = 'walk'
    moves: list[int] = Field(min_length=1)
    weights: list[int] = Field(min_length=1)
    boundary: Literal['wrap'] = 'wrap'
    start: Literal['lowest', 'move'] = 'lowest'
    on_remove: Literal['lowest', 'rank'] = 'lowest'

    @model_validator(mode='after')
    def weighted_moves(self) -> Self:
        if len(self.moves) != len(self.weights) or any(w <= 0 for w in self.weights):
            raise ValueError('walk weights must be positive and match moves')
        return self


class Grid(Model):
    kind: Literal['grid'] = 'grid'
    step: str

    @field_validator('step')
    @classmethod
    def beat_step(cls, value: str) -> str:
        return _beat_step(value)


class Euclidean(Model):
    kind: Literal['euclidean'] = 'euclidean'
    steps: int = Field(strict=True, ge=1)
    pulses: int = Field(strict=True, ge=0)
    rotation: int = Field(default=0, strict=True)
    step: str

    @field_validator('step')
    @classmethod
    def beat_step(cls, value: str) -> str:
        return _beat_step(value)

    @model_validator(mode='after')
    def pulse_count(self) -> Self:
        if self.pulses > self.steps:
            raise ValueError('pulses must not exceed steps')
        return self


class SourceRhythm(Model):
    kind: Literal['source'] = 'source'


class RhythmStep(Model):
    duration: str

    @field_validator('duration')
    @classmethod
    def beat_duration(cls, value: str) -> str:
        return _beat_step(value)


class HitStep(RhythmStep):
    kind: Literal['hit'] = 'hit'
    repeats: int = Field(default=1, strict=True, ge=1)


class RestStep(RhythmStep):
    kind: Literal['rest'] = 'rest'


class TieStep(RhythmStep):
    kind: Literal['tie'] = 'tie'


class Pattern(Model):
    kind: Literal['pattern'] = 'pattern'
    steps: list[
        Annotated[HitStep | RestStep | TieStep, Field(discriminator='kind')]
    ] = Field(min_length=1)


class Expression(Model):
    source: Literal['current', 'recorded'] = 'current'
    timing: Literal['original', 'fit'] = 'original'
    gaps: Literal['carry', 'omit'] = 'omit'


class Arpeggiator(Model):
    bank: Annotated[
        HeldBank | LatchedBank | HistoryBank | PhraseBank | RegionsBank,
        Field(discriminator='kind'),
    ] = HeldBank()
    selection: Annotated[
        Ascending
        | Descending
        | Played
        | Alternating
        | InsideOut
        | OutsideIn
        | IndexPattern
        | Shuffle
        | Choice
        | Walk,
        Field(discriminator='kind'),
    ] = Ascending()
    rhythm: Annotated[
        Grid | Euclidean | SourceRhythm | Pattern, Field(discriminator='kind')
    ]
    gate: Rational = Field(default=Fraction(4, 5), ge=0)
    probability: Rational = Field(default=Fraction(1), ge=0, le=1)
    retrigger: Literal['on_empty', 'bank_edit'] = 'on_empty'
    expression: Expression = Expression()
    seed: int | None = Field(default=None, strict=True)

    @model_validator(mode='after')
    def seeded_probability(self) -> Self:
        random_walk = isinstance(self.selection, Walk) and len(self.selection.moves) > 1
        if (
            0 < self.probability < 1
            or random_walk
            or isinstance(self.selection, (Shuffle, Choice))
        ) and self.seed is None:
            raise ValueError('random probability or selection requires a seed')
        return self


class ArpeggiatorScore(Score):
    kind: Literal['arpeggiator'] = 'arpeggiator'
    body: Arpeggiator


def _beat_step(value: str) -> str:
    if not value.endswith(' beat'):
        raise ValueError('step must be a positive rational beat duration')
    try:
        step = Fraction(value.removesuffix(' beat'))
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError('step must be a positive rational beat duration') from error
    if step <= 0:
        raise ValueError('step must be a positive rational beat duration')
    return f'{step} beat'
