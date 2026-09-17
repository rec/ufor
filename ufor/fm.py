"""Portable two-operator phase-modulation definitions; no audio rendering."""

from typing import Self

from pydantic import Field, model_validator

from . import control
from .base import Identifier, Model, unique
from .envelope import Envelope, Segment


class Operator(Model):
    name: Identifier
    ratio: float = Field(default=1, gt=0)
    tuning_cents: float = 0
    phase_cycles: float = Field(default=0, ge=0, lt=1)
    envelope: Envelope = Envelope(
        segments=[Segment(duration=0, target=1)],
        release=[Segment(duration=0, target=0)],
    )

    @model_validator(mode='after')
    def envelope_profile(self) -> Self:
        e = self.envelope
        if (
            e.clock != control.Clock.seconds
            or e.scope != control.Scope.voice
            or e.polarity != control.Polarity.unipolar
            or not e.hold
            or any(s.curve != 0 for s in [*e.segments, *e.release])
        ):
            raise ValueError(
                'FM operators require held linear unipolar voice envelopes'
            )
        return self


class Connection(Model):
    source: Identifier
    destination: Identifier
    index: float = Field(default=0, ge=0)


class FM(Model):
    operators: list[Operator] = Field(min_length=2, max_length=2)
    connection: Connection
    feedback: float = Field(default=0, ge=0)
    carrier_level: float = Field(default=1, ge=0)

    @model_validator(mode='after')
    def topology(self) -> Self:
        unique((o.name for o in self.operators), 'FM operator')
        c = self.connection
        if c.source == c.destination or {c.source, c.destination} != {
            o.name for o in self.operators
        }:
            raise ValueError('FM requires one connection between its two operators')
        return self
