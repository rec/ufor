"""Portable graph phase-modulation definitions; no audio rendering."""

from typing import Self

from pydantic import Field, model_validator

from . import control
from .base import Identifier, Model, unique
from .envelope import Envelope, Segment
from .oscillator import Waveform


class Operator(Model):
    name: Identifier
    ratio: float = Field(default=1, gt=0)
    tuning_cents: float = 0
    phase_cycles: float = Field(default=0, ge=0, lt=1)
    waveform: Waveform = Waveform.sine
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


class FMEdge(Model):
    name: Identifier | None = None
    source: Identifier
    destination: Identifier
    index: float = Field(default=0, ge=0)
    delayed: bool = False


class FM(Model):
    """A bounded phase-modulation graph with delayed feedback edges."""

    operators: list[Operator] = Field(min_length=2, max_length=6)
    edges: list[FMEdge] = Field(default_factory=list)
    carrier: Identifier
    carrier_level: float = Field(default=1, ge=0)

    @model_validator(mode='after')
    def topology(self) -> Self:
        unique((o.name for o in self.operators), 'FM operator')
        names = {o.name for o in self.operators}
        if self.carrier not in names:
            raise ValueError('FM carrier must name an operator')
        if any(e.source not in names or e.destination not in names for e in self.edges):
            raise ValueError('FM edge endpoint must name an operator')
        unique((edge_target_name(e) for e in self.edges), 'FM edge target')
        current = [(e.source, e.destination) for e in self.edges if not e.delayed]
        pending = {name: 0 for name in names}
        successors = {name: [] for name in names}
        for source, destination in current:
            pending[destination] += 1
            successors[source].append(destination)
        ready = [name for name in names if pending[name] == 0]
        visited = 0
        while ready:
            name = ready.pop()
            visited += 1
            for destination in successors[name]:
                pending[destination] -= 1
                if pending[destination] == 0:
                    ready.append(destination)
        if visited != len(names):
            raise ValueError('current-sample FM edges must be acyclic')
        return self


def edge_target_name(edge: FMEdge) -> Identifier:
    """Return the unambiguous modulation target name for an FM edge."""
    return edge.name or f'{edge.source}-{edge.destination}'
