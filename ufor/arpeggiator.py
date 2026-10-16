"""Portable arpeggiator profiles, independent of MIDI and audio devices."""

from enum import StrEnum, auto
from fractions import Fraction
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator
from reccy.configuration import units

from .base import Model
from .control import Rational
from .scale import Scale
from .score import Score
from .selector import parse_selector
from .tuning import Computed, IntervalPattern, RatioTable, Tuning


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


class Transition(Model, frozen=True):
    kind: Literal['transition'] = 'transition'
    weights: list[list[Annotated[int, Field(strict=True, ge=0, le=2**32 - 1)]]] = Field(
        min_length=1
    )
    missing_weight: int = Field(default=1, strict=True, ge=0, le=2**32 - 1)
    start: Literal['lowest', 'random'] = 'lowest'
    blocked: Literal['rest', 'uniform'] = 'rest'


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
    swing: Rational = Field(default=Fraction(1, 2), ge=0.5, lt=1)
    groove: list[Annotated[Rational, Field(gt=0)]] | None = Field(
        default=None, min_length=1
    )

    @field_validator('step')
    @classmethod
    def beat_step(cls, value: str) -> str:
        return _beat_step(value)

    @model_validator(mode='after')
    def exclusive_timing_shape(self) -> Self:
        if self.groove is not None and self.swing != Fraction(1, 2):
            raise ValueError('groove cannot be combined with non-straight swing')
        return self


class Euclidean(Model):
    kind: Literal['euclidean'] = 'euclidean'
    cycles: int | None = Field(default=None, strict=True, ge=1)
    swing: Rational = Field(default=Fraction(1, 2), ge=0.5, lt=1)
    groove: list[Annotated[Rational, Field(gt=0)]] | None = Field(
        default=None, min_length=1
    )
    steps: int = Field(strict=True, ge=1)
    pulses: int = Field(strict=True, ge=0)
    rotation: int = Field(default=0, strict=True)
    step: str

    @field_validator('step')
    @classmethod
    def beat_step(cls, value: str) -> str:
        return _beat_step(value)

    @model_validator(mode='after')
    def exclusive_timing_shape(self) -> Self:
        if self.groove is not None and self.swing != Fraction(1, 2):
            raise ValueError('groove cannot be combined with non-straight swing')
        return self

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


class PassCondition(Model, frozen=True):
    passes: list[Annotated[int, Field(strict=True, ge=1)]] = Field(min_length=1)
    out_of: int = Field(strict=True, ge=1)

    @model_validator(mode='after')
    def valid_passes(self) -> Self:
        if any(p > self.out_of for p in self.passes):
            raise ValueError('passes must not exceed out_of')
        if len(set(self.passes)) != len(self.passes):
            raise ValueError('passes must be unique')
        return self


class HitStep(RhythmStep):
    kind: Literal['hit'] = 'hit'
    repeats: int = Field(default=1, strict=True, ge=1)
    condition: PassCondition | None = None


class RestStep(RhythmStep):
    kind: Literal['rest'] = 'rest'


class TieStep(RhythmStep):
    kind: Literal['tie'] = 'tie'


class Pattern(Model):
    kind: Literal['pattern'] = 'pattern'
    cycles: int | None = Field(default=None, strict=True, ge=1)
    steps: list[
        Annotated[HitStep | RestStep | TieStep, Field(discriminator='kind')]
    ] = Field(min_length=1)


class StepPatterns(Model):
    accents: list[Annotated[Rational, Field(ge=0)]] = Field(
        default_factory=lambda: [Fraction(1)], min_length=1
    )
    gates: list[Annotated[Rational, Field(ge=0)]] = Field(
        default_factory=lambda: [Fraction(1)], min_length=1
    )


class ExpressionLane(StrEnum):
    breath = auto()
    bend = auto()
    pressure = auto()


class Expression(Model):
    source: Literal['current', 'recorded'] = 'current'
    timing: Literal['original', 'fit'] = 'original'
    gaps: Literal['carry', 'omit'] = 'omit'
    lanes: dict[ExpressionLane, Literal['current', 'recorded', 'envelfo']] = Field(
        default_factory=dict
    )


class Transposition(Model, frozen=True):
    semitones: Annotated[int, units.unit_validator('semitone')] = Field(
        default=0, strict=True, ge=-(2**63), le=2**63 - 1
    )
    boundary: Literal['drop', 'fold', 'error'] = 'drop'


class SelectionOffset(Model, frozen=True):
    ranks: int = Field(default=0, strict=True, ge=-(2**63), le=2**63 - 1)
    boundary: Literal['wrap', 'rest'] = 'wrap'


class ScaleMapping(StrEnum):
    nearest = auto()
    up = auto()
    down = auto()
    drop = auto()


class ScaleTransform(Model, frozen=True):
    definition: Scale
    degrees: int = Field(default=0, strict=True, ge=-(2**63), le=2**63 - 1)
    mapping: ScaleMapping = ScaleMapping.nearest

    @model_validator(mode='after')
    def usable_scale(self) -> Self:
        if self.definition.octave_length <= 0 or not self.definition.note_numbers:
            raise ValueError('scale mapping requires a nonempty, positive-period scale')
        return self


class PitchRegister(Model, frozen=True):
    low: int = Field(default=0, strict=True, ge=0, le=127)
    high: int = Field(default=127, strict=True, ge=0, le=127)
    boundary: Literal['drop', 'fold', 'error'] = 'drop'

    @model_validator(mode='after')
    def ordered_bounds(self) -> Self:
        if self.low > self.high:
            raise ValueError('register low must not exceed high')
        return self


class OctaveTraversal(StrEnum):
    notes_first = auto()
    octaves_first = auto()


class Octaves(Model, frozen=True):
    offsets: list[Annotated[int, Field(strict=True, ge=-(2**63), le=2**63 - 1)]] = (
        Field(default_factory=lambda: [0], min_length=1)
    )
    traversal: OctaveTraversal = OctaveTraversal.notes_first


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
        | Transition
        | Walk,
        Field(discriminator='kind'),
    ] = Ascending()
    rhythm: Annotated[
        Grid | Euclidean | SourceRhythm | Pattern, Field(discriminator='kind')
    ]
    gate: Rational = Field(default=Fraction(4, 5), ge=0)
    patterns: StepPatterns | None = None
    probability: Rational = Field(default=Fraction(1), ge=0, le=1)
    transposition: Transposition = Transposition()
    selection_offset: SelectionOffset = SelectionOffset()
    octaves: Octaves = Octaves()
    register_limits: PitchRegister | None = None
    scale: ScaleTransform | None = None
    tuning: Tuning | None = None
    bend_range: float | None = Field(default=None, gt=0)
    inversion: int = Field(default=0, strict=True, ge=-(2**63), le=2**63 - 1)
    voicing: (
        list[Annotated[int, Field(strict=True, ge=-(2**63), le=2**63 - 1)]] | None
    ) = Field(default=None, min_length=1)
    retrigger: Literal['on_empty', 'bank_edit'] = 'on_empty'
    expression: Expression = Expression()
    seed: int | None = Field(default=None, strict=True)

    @model_validator(mode='after')
    def seeded_probability(self) -> Self:
        if self.inversion and not isinstance(self.bank, (HeldBank, LatchedBank)):
            raise ValueError('inversion requires a held or latched bank')
        if self.voicing is not None and not isinstance(
            self.bank, (HeldBank, LatchedBank)
        ):
            raise ValueError('voicing requires a held or latched bank')
        if self.tuning is not None:
            if self.bend_range is None:
                raise ValueError(
                    'tuning requires an explicit MIDI bend_range in semitones'
                )
            source = self.tuning.source
            repeating = (
                isinstance(source, Computed)
                or (isinstance(source, RatioTable) and source.repeat_ratio is not None)
                or (isinstance(source, IntervalPattern) and source.repeat)
            )
            transforms = (
                self.inversion or any(self.octaves.offsets) or any(self.voicing or [])
            )
            folding = (
                self.register_limits.boundary
                if self.register_limits is not None
                else self.transposition.boundary
            ) == 'fold'
            if not repeating and (transforms or folding):
                raise ValueError(
                    'finite tunings cannot use period-based transforms or folding'
                )
        elif self.bend_range is not None:
            raise ValueError('bend_range requires tuning')
        random_walk = isinstance(self.selection, Walk) and len(self.selection.moves) > 1
        if (
            0 < self.probability < 1
            or random_walk
            or isinstance(self.selection, (Shuffle, Choice, Transition))
        ) and self.seed is None:
            raise ValueError('random probability or selection requires a seed')
        return self


class ArpeggiatorScore(Score):
    kind: Literal['arpeggiator'] = 'arpeggiator'
    body: Arpeggiator


def _beat_step(value: str) -> str:
    try:
        if units.quantity_unit(value) is None:
            raise ValueError('step must use an explicit unit')
        step = Fraction(str(units.magnitude(value, 'beat', exact=True)))
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError('step must be a positive rational beat duration') from error
    if step <= 0:
        raise ValueError('step must be a positive rational beat duration')
    return f'{step} beat'
