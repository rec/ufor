"""Native-timed stored events. Transport and performance state live in hosts."""

import base64
import binascii
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from .base import Identifier, Model


class Event(Model):
    tick: int = Field(strict=True)
    ordinal: int = Field(ge=0, strict=True)


class MidiEvent(Event):
    kind: Literal['midi'] = 'midi'
    data: list[Annotated[int, Field(strict=True)]] = Field(min_length=1)

    @field_validator('data')
    @classmethod
    def bytes_only(cls, value: list[int]) -> list[int]:
        if any(not 0 <= v <= 255 for v in value):
            raise ValueError('MIDI data must contain bytes')
        return value


class UmpEvent(Event):
    """One complete Universal MIDI Packet, stored as unsigned 32-bit words."""

    kind: Literal['ump'] = 'ump'
    words: list[Annotated[int, Field(strict=True, ge=0, le=0xFFFFFFFF)]] = Field(
        min_length=1, max_length=4
    )

    @model_validator(mode='after')
    def packet_length(self) -> Self:
        if len(self.words) != _UMP_WORD_COUNTS[self.message_type]:
            raise ValueError('UMP word count does not match message type')
        return self

    @property
    def message_type(self) -> int:
        return self.words[0] >> 28

    @property
    def group(self) -> int | None:
        """Zero-based wire group for known grouped types; unknown types stay opaque."""
        return (
            (self.words[0] >> 24) & 15
            if self.message_type in (1, 2, 3, 4, 5, 13)
            else None
        )

    @property
    def sysex_format(self) -> Literal['sysex7', 'sysex8'] | None:
        if (self.words[0] >> 20) & 15 <= 3:
            if self.message_type == 3:
                return 'sysex7'
            if self.message_type == 5:
                return 'sysex8'
        return None


class OscMessage(Model):
    path: str
    types: str
    args: list[str | int | float | bool | None]


class OscDecodeError(Model):
    error: str


class Endpoint(Model):
    host: str
    port: int = Field(ge=0, le=65535)


class OscEvent(Event):
    kind: Literal['osc'] = 'osc'
    data_b64: str
    direction: Literal['in', 'out']
    source_time: str | None = None
    endpoint: Endpoint | None = None
    decoded: list[OscMessage | OscDecodeError] = Field(default_factory=list)
    reason: str | None = None

    @field_validator('data_b64')
    @classmethod
    def packet_bytes(cls, value: str) -> str:
        try:
            base64.b64decode(value, validate=True)
        except binascii.Error as error:
            raise ValueError('OSC packet must be valid base64') from error
        return value


class KeyEvent(Event):
    kind: Literal['key'] = 'key'
    key: str = Field(min_length=1)
    action: Literal['press', 'release']
    text: str | None = None
    modifiers: list[str] = Field(default_factory=list)
    repeat: bool = False


class Trigger(Event):
    kind: Literal['trigger'] = 'trigger'
    part: Identifier
    trigger_id: Identifier
    key: int = Field(strict=True)
    velocity: float = Field(default=1, strict=True, ge=0, le=1)
    pitch_hz: float | None = Field(default=None, strict=True, gt=0)
    controls: dict[Identifier, Annotated[float, Field(strict=True, ge=-1, le=1)]] = (
        Field(default_factory=dict)
    )


class Release(Event):
    kind: Literal['release'] = 'release'
    part: Identifier
    trigger_id: Identifier


class ControlChange(Event):
    kind: Literal['control_change'] = 'control_change'
    control: Identifier
    value: float = Field(strict=True, ge=-1, le=1)
    scope: Literal['instrument', 'part', 'trigger']
    part: Identifier | None = None
    trigger_id: Identifier | None = None

    @model_validator(mode='after')
    def addressed_scope(self) -> Self:
        if self.scope == 'instrument':
            if self.part is not None or self.trigger_id is not None:
                raise ValueError('Instrument controls have no part or trigger_id')
        elif self.part is None:
            raise ValueError('Part and trigger controls require part')
        if self.scope == 'trigger':
            if self.trigger_id is None:
                raise ValueError('Trigger controls require trigger_id')
        elif self.trigger_id is not None:
            raise ValueError('trigger_id is only allowed for trigger controls')
        return self


PerformanceEvent = Annotated[
    Trigger | Release | ControlChange, Field(discriminator='kind')
]
StoredEvent = Annotated[
    MidiEvent | UmpEvent | OscEvent | KeyEvent | Trigger | Release | ControlChange,
    Field(discriminator='kind'),
]


_UMP_WORD_COUNTS = (1, 1, 1, 2, 2, 4, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4)
