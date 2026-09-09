"""A native event sequence has an explicit extent independent of event count."""

from typing import Literal, Self

from pydantic import Field, model_validator

from .base import Identifier, Model, unique
from .events import StoredEvent
from .interface import Direction, EventType, InterfaceDocument, SequenceBinding
from .time import Timebase


class Sequence(Model):
    timebase: Identifier
    start: int = Field(default=0, strict=True)
    end: int = Field(strict=True)
    events: list[StoredEvent] = Field(default_factory=list)

    @model_validator(mode='after')
    def event_order(self) -> Self:
        if self.end < self.start:
            raise ValueError('sequence end precedes its start')
        unique([str(e.ordinal) for e in self.events], 'event ordinals')
        order = [(e.tick, e.ordinal) for e in self.events]
        if order != sorted(order):
            raise ValueError('events must be in timestamp and ordinal order')
        if any(not self.start <= e.tick < self.end for e in self.events):
            raise ValueError('event is outside the sequence extent')
        return self


class SequenceDocument(InterfaceDocument):
    kind: Literal['sequence'] = 'sequence'
    timebases: list[Timebase] = Field(min_length=1)
    body: Sequence

    @model_validator(mode='after')
    def clock_reference(self) -> Self:
        unique([t.id for t in self.timebases], 'timebase IDs')
        if self.body.timebase not in {t.id for t in self.timebases}:
            raise ValueError('sequence references an unknown timebase')
        if self.parameters:
            raise ValueError('sequences have no configurable parameters')
        for port in self.ports:
            if (
                port.direction != Direction.output
                or not isinstance(port.binding, SequenceBinding)
                or not isinstance(port.stream, EventType)
                or port.stream.timebase != self.body.timebase
                or any(e.kind not in port.stream.kinds for e in self.body.events)
            ):
                raise ValueError('sequence export must match its native event body')
        return self
