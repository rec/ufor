"""Lossless event-ledger references for captured arpeggiator note material."""

from fractions import Fraction
from typing import Annotated, Self

from pydantic import Field, model_validator
from reccy.configuration import units

from .base import Identifier, Model, UnitInterval, unique
from .control import Clock, Rational
from .events import StoredEvent
from .samples.playback import Slice
from .time import Timebase


class EntryState(Model):
    """A known controller value, or an explicitly unknown initial value."""

    value: float | None = Field(default=None, ge=-1, le=1)
    source_event: int | None = Field(default=None, strict=True, ge=0)

    @model_validator(mode='after')
    def known_source(self) -> Self:
        if self.value is None and self.source_event is not None:
            raise ValueError('unknown entry state cannot have a source event')
        return self


class SourceNote(Model):
    """One immutable source identity; event references index the phrase ledger."""

    capture_id: Identifier
    note_id: Identifier
    onset_tick: Annotated[int, units.unit_validator('tick')] = Field(strict=True, ge=0)
    gate_end_tick: Annotated[int, units.unit_validator('tick')] = Field(
        strict=True, ge=0
    )
    cell_end_tick: Annotated[int, units.unit_validator('tick')] = Field(
        strict=True, ge=0
    )
    onset_event: int | None = Field(default=None, strict=True, ge=0)
    release_event: int | None = Field(default=None, strict=True, ge=0)
    expression_events: list[Annotated[int, Field(strict=True, ge=0)]] = Field(
        default_factory=list
    )
    following_events: list[Annotated[int, Field(strict=True, ge=0)]] = Field(
        default_factory=list
    )
    entry_state: dict[Identifier, EntryState] = Field(default_factory=dict)
    key: int | None = Field(default=None, strict=True)
    selection_key: int | None = Field(default=None, strict=True)
    velocity: UnitInterval | None = None
    release_velocity: UnitInterval | None = None
    region: Slice | None = None

    @model_validator(mode='after')
    def time_intervals(self) -> Self:
        if self.gate_end_tick < self.onset_tick:
            raise ValueError('gate end precedes note onset')
        if self.cell_end_tick <= self.onset_tick:
            raise ValueError('cell end must follow note onset')
        if self.key is None and self.selection_key is None:
            raise ValueError('source note requires a key or selection key')
        return self


class CapturedPhrase(Model):
    """One ledger and notes that reference it without copying source events."""

    capture_id: Identifier
    timebase: Timebase
    end_tick: Annotated[int, units.unit_validator('tick')] = Field(strict=True, ge=0)
    events: list[StoredEvent] = Field(default_factory=list)
    notes: list[SourceNote] = Field(default_factory=list)
    prefix_events: list[Annotated[int, Field(strict=True, ge=0)]] = Field(
        default_factory=list
    )

    @model_validator(mode='after')
    def ledger_references(self) -> Self:
        unique((n.note_id for n in self.notes), 'source note ID')
        if any(n.capture_id != self.capture_id for n in self.notes):
            raise ValueError('source note belongs to another capture')
        if any(n.cell_end_tick > self.end_tick for n in self.notes):
            raise ValueError('source note cell exceeds phrase end')
        if any(n.gate_end_tick > self.end_tick for n in self.notes):
            raise ValueError('source note gate exceeds phrase end')
        if any(e.tick > self.end_tick for e in self.events):
            raise ValueError('source event exceeds phrase end')
        if any(
            (b.tick, b.ordinal) <= (a.tick, a.ordinal)
            for a, b in zip(self.events, self.events[1:], strict=False)
        ):
            raise ValueError('source events must increase in (tick, ordinal) order')
        references = list(self.prefix_events)
        for note in self.notes:
            references.extend(note.expression_events)
            references.extend(note.following_events)
            references.extend(
                r for r in (note.onset_event, note.release_event) if r is not None
            )
            references.extend(
                s.source_event
                for s in note.entry_state.values()
                if s.source_event is not None
            )
        if any(r >= len(self.events) for r in references):
            raise ValueError('source event reference is outside the phrase ledger')
        for note in self.notes:
            if note.onset_event is not None and (
                self.events[note.onset_event].tick != note.onset_tick
            ):
                raise ValueError('onset event must match note onset')
            if note.release_event is not None and (
                self.events[note.release_event].tick != note.gate_end_tick
            ):
                raise ValueError('release event must match note gate end')
            if any(
                self.events[r].tick > note.onset_tick
                for s in note.entry_state.values()
                if (r := s.source_event) is not None
            ):
                raise ValueError('entry state cannot observe a future event')
            if any(
                self.events[r].tick < note.onset_tick for r in note.expression_events
            ):
                raise ValueError('note expression precedes note onset')
            if any(
                not note.gate_end_tick <= self.events[r].tick < note.cell_end_tick
                for r in note.following_events
            ):
                raise ValueError('following event is outside the note gap')
        return self


class Occurrence(Model):
    """One output lifetime selected from a source note and bank revision."""

    source_capture: Identifier
    source_note: Identifier
    bank_revision: int = Field(strict=True, ge=0)
    decision: int = Field(strict=True, ge=0)
    destination: Identifier
    trigger_id: Identifier
    clock: Clock
    onset: Rational = Field(ge=0)
    gate_end: Rational = Field(ge=0)
    transposition_cents: Annotated[
        Rational, units.unit_validator('musical_cent', exact=True)
    ] = Fraction(0)

    @model_validator(mode='before')
    @classmethod
    def clock_units(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        unit = 'beat' if value.get('clock') == Clock.beats else 'second'
        return dict(value) | {
            f: units.magnitude(value[f], unit, exact=True)
            for f in ['onset', 'gate_end']
            if f in value and isinstance(value[f], str)
        }

    @model_validator(mode='after')
    def gate_interval(self) -> Self:
        if self.gate_end < self.onset:
            raise ValueError('output gate end precedes onset')
        return self
