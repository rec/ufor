"""Alternate takes, choking, sustain, and deterministic selection state."""

from hashlib import sha256
from typing import Self

from pydantic import Field, StrictBool, model_validator

from ..base import (
    Bipolar,
    Identifier,
    Model,
    NoteKey,
    PositiveSeconds,
    UnitInterval,
    unique,
)
from . import enums


class Selection(Model):
    name: Identifier
    mode: enums.SelectionMode


class RandomRange(Model):
    """A half-open interval selected by one seeded draw per input event."""

    minimum: UnitInterval = 0
    maximum: UnitInterval = 1

    @model_validator(mode='after')
    def nonempty_range(self) -> Self:
        if self.minimum >= self.maximum:
            raise ValueError('random range must not be empty')
        return self

    def contains(self, value: float) -> bool:
        return self.minimum <= value < self.maximum


class SelectionSequence(Model):
    """One state partition for a named selection set and eligible slot IDs."""

    part: Identifier
    selection: Identifier
    trigger: enums.TriggerKind
    key: NoteKey
    candidates: list[Identifier] = Field(min_length=1)
    counter: int = Field(default=0, ge=0)
    remaining: list[Identifier] = Field(default_factory=list)
    previous: Identifier | None = None

    @model_validator(mode='after')
    def sequence_values(self) -> Self:
        if self.candidates != sorted(self.candidates):
            raise ValueError('candidates must be sorted')
        unique(self.candidates, 'candidate ID')
        if any(c not in self.candidates for c in self.remaining):
            raise ValueError('remaining choices must be candidates')
        unique(self.remaining, 'remaining choice')
        if self.previous is not None and self.previous not in self.candidates:
            raise ValueError('previous choice must be a candidate')
        return self


class SelectionState(Model):
    """Serializable state reset from an explicit performance seed."""

    seed: int = Field(strict=True, ge=0, lt=2**64)
    sequences: list[SelectionSequence] = Field(default_factory=list)

    @model_validator(mode='after')
    def unique_sequences(self) -> Self:
        unique(
            (
                (s.part, s.selection, s.trigger, s.key, tuple(s.candidates))
                for s in self.sequences
            ),
            'selection state partition',
        )
        return self


def choose(
    selection: Selection,
    state: SelectionState,
    part: str,
    trigger: enums.TriggerKind,
    key: int,
    candidates: list[str],
) -> tuple[str, SelectionState]:
    """Choose one stable candidate and return its replacement state."""
    ordered = sorted(candidates)
    unique(ordered, 'candidate ID')
    if not ordered:
        raise ValueError('selection requires at least one candidate')
    sequence = next(
        (
            s
            for s in state.sequences
            if (s.part, s.selection, s.trigger, s.key, s.candidates)
            == (part, selection.name, trigger, key, ordered)
        ),
        SelectionSequence(
            part=part,
            selection=selection.name,
            trigger=trigger,
            key=key,
            candidates=ordered,
        ),
    )
    if selection.mode == enums.SelectionMode.cycle:
        choice = ordered[sequence.counter % len(ordered)]
        next_sequence = sequence.model_copy(update={'counter': sequence.counter + 1})
    elif selection.mode == enums.SelectionMode.random:
        choice = ordered[_index(state.seed, sequence, len(ordered), sequence.counter)]
        next_sequence = sequence.model_copy(update={'counter': sequence.counter + 1})
    else:
        remaining = sequence.remaining
        counter = sequence.counter
        if not remaining:
            remaining, counter = _shuffle(state.seed, sequence, counter)
        choice = remaining[0]
        next_sequence = sequence.model_copy(
            update={
                'counter': counter,
                'remaining': remaining[1:],
                'previous': choice,
            }
        )
    sequences = [s for s in state.sequences if s != sequence]
    sequences.append(next_sequence)
    return choice, state.model_copy(update={'sequences': sequences})


def random_range_value(
    seed: int,
    part: str,
    trigger_id: str | None,
    tick: int,
    ordinal: int,
) -> float:
    """Return the shared random condition value for one input event."""
    digest = sha256()
    for value in (
        'sample-random-range-v1',
        str(seed),
        part,
        trigger_id or '',
        str(tick),
        str(ordinal),
    ):
        encoded = value.encode()
        digest.update(len(encoded).to_bytes(4, 'big'))
        digest.update(encoded)
    return int.from_bytes(digest.digest()[:7], 'big') / 2**56


def _shuffle(
    seed: int, sequence: SelectionSequence, counter: int
) -> tuple[list[str], int]:
    candidates = sequence.candidates.copy()
    start = 0
    if len(candidates) > 1 and sequence.previous is not None:
        first_candidates = [c for c in candidates if c != sequence.previous]
        first = first_candidates[
            _index(seed, sequence, len(first_candidates), counter, sequence.previous)
        ]
        candidates.remove(first)
        candidates.insert(0, first)
        counter += 1
        start = 1
    for index in range(len(candidates) - 1, start, -1):
        swap = start + _index(seed, sequence, index - start + 1, counter)
        candidates[index], candidates[swap] = candidates[swap], candidates[index]
        counter += 1
    return candidates, counter


def _index(
    seed: int,
    sequence: SelectionSequence,
    bound: int,
    counter: int,
    excluded: str | None = None,
) -> int:
    values = (
        str(seed),
        sequence.part,
        sequence.selection,
        sequence.trigger.value,
        str(sequence.key),
        *sequence.candidates,
        str(counter),
        excluded or '',
    )
    limit = 1 << 256
    retry = 0
    while True:
        digest = sha256()
        for value in (*values, str(retry)):
            encoded = value.encode()
            digest.update(len(encoded).to_bytes(4, 'big'))
            digest.update(encoded)
        value = int.from_bytes(digest.digest(), 'big')
        acceptable = limit - limit % bound
        if value < acceptable:
            return value % bound
        retry += 1


class Choke(Model):
    group: Identifier
    mode: enums.ChokeMode
    fade_seconds: PositiveSeconds | None = None

    @model_validator(mode='after')
    def fade_time_matches_mode(self) -> Self:
        if self.mode == enums.ChokeMode.fade:
            if self.fade_seconds is None:
                raise ValueError('fade requires fade_seconds')
        elif self.fade_seconds is not None:
            raise ValueError('fade_seconds is only allowed for fade')
        return self


class VoicePolicy(Model):
    maximum_voices: int = Field(strict=True, gt=0)
    same_key: enums.SameKey = enums.SameKey.stack
    overflow: enums.VoiceOverflow = enums.VoiceOverflow.release_oldest


class Sustain(Model):
    control: Identifier
    threshold: UnitInterval = Field(default=0.5, gt=0)


class KeySwitch(Model):
    key: NoteKey
    articulation: Identifier
    behavior: enums.KeyBehavior = enums.KeyBehavior.latched
    consume: StrictBool = True


class ControlSwitch(Model):
    control: Identifier
    minimum_value: Bipolar
    maximum_value: Bipolar
    articulation: Identifier

    @model_validator(mode='after')
    def ordered_range(self) -> Self:
        if self.minimum_value > self.maximum_value:
            raise ValueError('minimum_value must not exceed maximum_value')
        return self


class Articulations(Model):
    ids: list[Identifier] = Field(min_length=1)
    default: Identifier
    keys: list[KeySwitch] = Field(default_factory=list)
    controls: list[ControlSwitch] = Field(default_factory=list)

    @model_validator(mode='after')
    def valid_switches(self) -> Self:
        unique(self.ids, 'articulation ID')
        unique((k.key for k in self.keys), 'keyswitch key')
        references = [
            self.default,
            *(k.articulation for k in self.keys),
            *(c.articulation for c in self.controls),
        ]
        if missing := set(references).difference(self.ids):
            raise ValueError(f'Unknown articulations: {sorted(missing)}')
        previous: ControlSwitch | None = None
        for switch in sorted(self.controls, key=lambda c: (c.control, c.minimum_value)):
            if (
                previous is not None
                and switch.control == previous.control
                and switch.minimum_value <= previous.maximum_value
            ):
                raise ValueError(
                    f'Overlapping articulation ranges for control {switch.control}'
                )
            previous = switch
        return self
