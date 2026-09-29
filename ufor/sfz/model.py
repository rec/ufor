"""SFZ data types and channel mapping shared by import and export."""

import math
from typing import Annotated, Literal

from pydantic import Field

from .. import base
from ..interface import ScoreReference
from ..performance_binding import PerformanceBindingScore
from ..samples import processing
from ..samples.instrument import SampleInstrumentScore


class SfzLocation(base.Model):
    kind: Literal['sfz'] = 'sfz'
    header: str
    opcode: str | None
    line: int
    column: int


class InstrumentLocation(base.Model):
    kind: Literal['instrument'] = 'instrument'
    path: str


class UnimplementedFeature(base.Model):
    location: Annotated[SfzLocation | InstrumentLocation, Field(discriminator='kind')]
    value: str | None
    reason: str


class SfzCompileResult(base.Model):
    instrument: SampleInstrumentScore | None
    binding: PerformanceBindingScore | None = None
    unimplemented: list[UnimplementedFeature] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.unimplemented


class SfzExportResult(base.Model):
    contents: str
    unimplemented: list[UnimplementedFeature] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.unimplemented


class ParsedOpcode(base.Model):
    header: str
    opcode: str
    value: str
    line: int
    column: int


class ParsedRegion(base.Model):
    default_path: str
    opcodes: list[ParsedOpcode]
    line: int


class Opcode(base.Model):
    name: str
    value: str


class InstrumentMetadata(base.Model):
    version: Literal[2]
    title: str
    description: str | None
    tags: list[str]


class SlotMetadata(base.Model):
    name: str
    title: str | None
    description: str | None
    tags: list[str]


class SfzSource(base.Model):
    regions: list[ParsedRegion]
    instrument_metadata: dict[str, object]
    slot_metadata: dict[int, dict[str, object]]
    unimplemented: list[UnimplementedFeature]


class SfzMidiBindingRequest(base.Model):
    instrument: ScoreReference
    part: base.Identifier
    repeated_key_release: Literal['oldest', 'newest']


def _channel_routes(channels: int, outputs: list[str]) -> list[processing.ChannelRoute]:
    inputs = (
        ['mono']
        if channels == 1
        else ['left', 'right']
        if channels == 2
        else [f'channel-{i}' for i in range(1, channels + 1)]
    )
    if inputs == outputs:
        return [processing.ChannelRoute(input=c, output=c, gain=1) for c in inputs]
    if inputs == ['mono'] and outputs == ['left', 'right']:
        return [
            processing.ChannelRoute(input='mono', output=c, gain=math.sqrt(0.5))
            for c in outputs
        ]
    raise ValueError('SFZ import requires matching channels or mono-to-stereo output')
