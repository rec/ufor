"""Lossless TX81Z voice-dump inspection, including additional operator data."""

from functools import cached_property

from pydantic import Field, field_validator

from .base import Model


class TX81ZVoice(Model):
    """One validated 93-byte TX81Z VCED voice payload."""

    data: bytes = Field(strict=True)

    @field_validator('data')
    @classmethod
    def valid_data(cls, value: bytes) -> bytes:
        if len(value) != 93 or any(byte >= 128 for byte in value):
            raise ValueError('TX81Z VCED data must contain 93 seven-bit bytes')
        return value


class TX81ZAdditional(Model):
    """One validated 23-byte TX81Z ACED payload, including waveform settings."""

    data: bytes = Field(strict=True)

    @field_validator('data')
    @classmethod
    def valid_data(cls, value: bytes) -> bytes:
        if len(value) != 23 or any(byte >= 128 for byte in value):
            raise ValueError('TX81Z ACED data must contain 23 seven-bit bytes')
        return value


class TX81ZEntry(Model):
    """One complete message or opaque span at its original byte offset."""

    offset: int = Field(strict=True, ge=0)
    data: bytes = Field(strict=True, min_length=1)

    @cached_property
    def diagnostic(self) -> str | None:
        """Why this entry is not a supported TX81Z voice message, if applicable."""
        return _diagnostic(self.data)

    @cached_property
    def voice(self) -> TX81ZVoice | None:
        """Decoded VCED payload, or None for ACED and unsupported entries."""
        return (
            TX81ZVoice(data=self.data[6:-2])
            if self.diagnostic is None and self.data[3] == 3
            else None
        )

    @cached_property
    def additional(self) -> TX81ZAdditional | None:
        """Decoded ACED payload, or None for VCED and unsupported entries."""
        return (
            TX81ZAdditional(data=self.data[16:-2])
            if self.diagnostic is None and self.data[3] == 0x7E
            else None
        )


def parse_tx81z(data: bytes) -> list[TX81ZEntry]:
    """Partition a dump without losing opaque bytes or malformed messages."""
    entries: list[TX81ZEntry] = []
    start = 0
    for index, value in enumerate(data):
        if value == 0xF0 and index > start:
            entries.append(TX81ZEntry(offset=start, data=data[start:index]))
            start = index
        elif value == 0xF7:
            entries.append(TX81ZEntry(offset=start, data=data[start : index + 1]))
            start = index + 1
    if start < len(data):
        entries.append(TX81ZEntry(offset=start, data=data[start:]))
    return entries


def _diagnostic(data: bytes) -> str | None:
    if not data or data[0] != 0xF0 or data[-1] != 0xF7:
        return 'missing SysEx framing (F0 ... F7)'
    if any(byte >= 128 for byte in data[1:-1]):
        return 'SysEx interior contains non-seven-bit data'
    if len(data) < 8 or data[1] != 0x43 or data[2] > 15:
        return 'unsupported Yamaha TX81Z bulk header'
    if data[3:6] == bytes([3, 0, 93]):
        payload = data[6:-2]
        if len(payload) != 93:
            return 'TX81Z VCED message length does not match its byte count'
    elif data[3:6] == bytes([0x7E, 0, 33]):
        if len(data) != 41 or data[6:16] != b'LM  8976AE':
            return 'unsupported TX81Z ACED message'
        payload = data[6:-2]
    else:
        return 'unsupported TX81Z voice message'
    if data[-2] != -sum(payload) % 128:
        return 'invalid TX81Z checksum'
    return None
