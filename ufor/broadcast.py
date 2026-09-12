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


class ProgrammeSource(Model):
    name: Identifier
    kind: SourceKind


class Section(Model):
    name: Identifier
    source: Identifier
    start: Literal['at', 'after', 'cue']
    tick: int | None = Field(default=None, ge=0, strict=True)
    after: Identifier | None = None
    cue: Identifier | None = None
    duration: int = Field(gt=0, strict=True)
    replacement: Identifier | None = None
    capture: bool = False

    @model_validator(mode='after')
    def start_rule(self) -> Self:
        values = [self.tick is not None, self.after is not None, self.cue is not None]
        if (
            sum(values) != 1
            or (self.start == 'at' and not values[0])
            or (self.start == 'after' and not values[1])
            or (self.start == 'cue' and not values[2])
        ):
            raise ValueError('section start must match exactly one start rule')
        return self


class AiredEvent(Model):
    tick: int = Field(ge=0, strict=True)
    ordinal: int = Field(ge=0, strict=True)
    section: Identifier
    action: Literal['start', 'end', 'replacement', 'cue', 'dropout']


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
            or s.replacement is not None
            and s.replacement not in sources
            for s in self.sections
        ):
            raise ValueError('section references an unknown source')
        if any(s.after is not None and s.after not in names for s in self.sections):
            raise ValueError('after start references an unknown section')
        try:
            list(
                TopologicalSorter(
                    {s.name: [s.after] if s.after else [] for s in self.sections}
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
