"""Planned radio programmes and immutable as-aired decisions."""

from enum import StrEnum, auto
from graphlib import CycleError, TopologicalSorter
from typing import Literal, Self

from pydantic import Field, model_validator

from .base import Identifier, Model, unique
from .score import Score
from .time import Timebase


class SourceKind(StrEnum):
    recorded = auto()
    live = auto()
    relay = auto()


class StartKind(StrEnum):
    at = auto()
    after = auto()
    cue = auto()


class EndKind(StrEnum):
    duration = auto()
    at = auto()
    cue_or_source_end = auto()


class ProgrammeSource(Model):
    name: Identifier
    kind: SourceKind
    relay_buffer: int | None = Field(default=None, gt=0, strict=True)

    @model_validator(mode='after')
    def relay_contract(self) -> Self:
        if (self.kind == SourceKind.relay) != (self.relay_buffer is not None):
            raise ValueError('only relays declare a required buffer')
        return self


class StartRule(Model):
    kind: StartKind
    tick: int | None = Field(default=None, ge=0, strict=True)
    section: Identifier | None = None
    cue: Identifier | None = None
    earliest: int | None = Field(default=None, ge=0, strict=True)
    deadline: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode='after')
    def selection(self) -> Self:
        if (
            self.kind == StartKind.at
            and self.tick is not None
            and self.section is None
            and self.cue is None
        ):
            return self
        if (
            self.kind == StartKind.after
            and self.section is not None
            and self.tick is None
            and self.cue is None
        ):
            return self
        if (
            self.kind == StartKind.cue
            and self.cue is not None
            and self.tick is None
            and self.section is None
        ):
            if self.deadline is not None and self.deadline < (self.earliest or 0):
                raise ValueError('cue deadline must not precede earliest tick')
            return self
        raise ValueError('start rule fields do not match its kind')


class EndRule(Model):
    kind: EndKind
    tick: int | None = Field(default=None, ge=0, strict=True)
    duration: int | None = Field(default=None, gt=0, strict=True)
    cue: Identifier | None = None
    maximum: int | None = Field(default=None, gt=0, strict=True)

    @model_validator(mode='after')
    def selection(self) -> Self:
        if (
            self.kind == EndKind.duration
            and self.duration is not None
            and self.tick is None
            and self.cue is None
            and self.maximum is None
        ):
            return self
        if (
            self.kind == EndKind.at
            and self.tick is not None
            and self.duration is None
            and self.cue is None
            and self.maximum is None
        ):
            return self
        if (
            self.kind == EndKind.cue_or_source_end
            and self.maximum is not None
            and self.tick is None
            and self.duration is None
        ):
            return self
        raise ValueError('end rule fields do not match its kind')


class Transition(Model):
    kind: Literal['cut', 'crossfade', 'mix'] = 'cut'
    duration: int = Field(default=0, ge=0, strict=True)

    @model_validator(mode='after')
    def duration_contract(self) -> Self:
        if self.kind == 'cut' and self.duration != 0:
            raise ValueError('a cut has no duration')
        return self


class Unavailable(Model):
    kind: Literal['replacement', 'skip', 'stop']
    source: Identifier | None = None

    @model_validator(mode='after')
    def source_contract(self) -> Self:
        if (self.kind == 'replacement') != (self.source is not None):
            raise ValueError('only replacement availability names a source')
        return self


class Section(Model):
    name: Identifier
    source: Identifier
    start: StartRule
    end: EndRule
    transition: Transition = Transition()
    unavailable: Unavailable = Unavailable(kind='stop')
    late_join: Literal['current', 'from_start', 'reject'] = 'current'
    capture: bool = False


class AiredEvent(Model):
    tick: int = Field(ge=0, strict=True)
    ordinal: int = Field(ge=0, strict=True)
    section: Identifier
    action: Literal[
        'start',
        'end',
        'replacement',
        'cue',
        'dropout',
        'submitted',
        'delivered',
        'failed',
    ]
    source_instance: Identifier | None = None
    detail: str | None = None


class AiredRun(Model):
    events: list[AiredEvent] = Field(min_length=1)

    @model_validator(mode='after')
    def ordered(self) -> Self:
        if [(e.tick, e.ordinal) for e in self.events] != sorted(
            (e.tick, e.ordinal) for e in self.events
        ):
            raise ValueError('as-aired events must be ordered')
        unique((str(e.ordinal) for e in self.events), 'as-aired ordinal')
        return self


class Broadcast(Model):
    sources: list[ProgrammeSource] = Field(min_length=1)
    sections: list[Section] = Field(min_length=1)
    aired: AiredRun | None = None

    @model_validator(mode='after')
    def structure(self) -> Self:
        unique((s.name for s in self.sources), 'programme source')
        unique((s.name for s in self.sections), 'programme section')
        sources = {s.name for s in self.sources}
        names = {s.name for s in self.sections}
        if any(
            s.source not in sources
            or s.unavailable.source is not None
            and s.unavailable.source not in sources
            for s in self.sections
        ):
            raise ValueError('section references an unknown source')
        if any(
            s.start.section is not None and s.start.section not in names
            for s in self.sections
        ):
            raise ValueError('after start references an unknown section')
        try:
            list(
                TopologicalSorter(
                    {
                        s.name: [s.start.section] if s.start.section else []
                        for s in self.sections
                    }
                ).static_order()
            )
        except CycleError as error:
            raise ValueError('after start cycle') from error
        if self.aired is not None and any(
            e.section not in names for e in self.aired.events
        ):
            raise ValueError('as-aired event references an unknown section')
        return self


class BroadcastScore(Score):
    kind: Literal['broadcast'] = 'broadcast'
    timebase: Timebase
    body: Broadcast


def provisional_sections(broadcast: Broadcast) -> list[Identifier]:
    """Return sections that cannot have a complete time without a live cue."""
    return [
        section.name
        for section in broadcast.sections
        if section.start.kind == StartKind.cue
        or section.end.kind == EndKind.cue_or_source_end
    ]
