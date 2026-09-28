"""Lossless DX7 voice-dump inspection, without synthesis or device access."""

from functools import cached_property

from pydantic import Field, field_validator

from .base import Model


class DX7Voice(Model):
    """One validated DX7 voice in Yamaha's edit or packed-bank representation."""

    data: bytes = Field(strict=True)

    @field_validator('data')
    @classmethod
    def valid_data(cls, value: bytes) -> bytes:
        if len(value) not in (128, 155) or any(byte >= 128 for byte in value):
            raise ValueError('DX7 voice data must contain 128 or 155 seven-bit bytes')
        return value

    @property
    def packed(self) -> bool:
        """Whether data is the 128-byte representation used in a 32-voice bank."""
        return len(self.data) == 128

    @property
    def algorithm(self) -> int:
        """The documented one-based Yamaha algorithm number, from 1 through 32."""
        return self.data[110 if self.packed else 134] + 1

    @property
    def feedback(self) -> int:
        """The documented feedback setting, from 0 through 7."""
        return (self.data[111] & 7) if self.packed else self.data[135]

    @property
    def title(self) -> str:
        """The ten stored ASCII title bytes, including spaces and control bytes."""
        start = 118 if self.packed else 145
        return self.data[start : start + 10].decode('ascii')


class DX7Entry(Model):
    """One complete message or opaque span at its original byte offset."""

    offset: int = Field(strict=True, ge=0)
    data: bytes = Field(strict=True, min_length=1)

    @cached_property
    def diagnostic(self) -> str | None:
        """Why the entry cannot be decoded as a DX7 voice message, if applicable."""
        return _diagnostic(self.data)

    @cached_property
    def voices(self) -> list[DX7Voice] | None:
        """Decoded voices, or None when this entry is not a supported DX7 message."""
        if self.diagnostic is not None:
            return None
        payload = self.data[6:-2]
        if len(payload) == 155:
            return [DX7Voice(data=payload)]
        return [
            DX7Voice(data=payload[index : index + 128]) for index in range(0, 4096, 128)
        ]


def parse_dx7(data: bytes) -> list[DX7Entry]:
    """Partition a dump without losing opaque bytes or malformed messages."""
    entries: list[DX7Entry] = []
    start = 0
    for index, value in enumerate(data):
        if value == 0xF0 and index > start:
            entries.append(DX7Entry(offset=start, data=data[start:index]))
            start = index
        elif value == 0xF7:
            entries.append(DX7Entry(offset=start, data=data[start : index + 1]))
            start = index + 1
    if start < len(data):
        entries.append(DX7Entry(offset=start, data=data[start:]))
    return entries


def _diagnostic(data: bytes) -> str | None:
    if not data or data[0] != 0xF0 or data[-1] != 0xF7:
        return 'missing SysEx framing (F0 ... F7)'
    if any(byte >= 128 for byte in data[1:-1]):
        return 'SysEx interior contains non-seven-bit data'
    if len(data) < 8 or data[1] != 0x43 or data[2] > 15:
        return 'unsupported Yamaha DX7 bulk header'
    format = data[3]
    count = data[4] << 7 | data[5]
    if (format, count) not in ((0, 155), (9, 4096)):
        return 'unsupported DX7 bulk format'
    if len(data) != count + 8:
        return 'DX7 message length does not match its byte count'
    if data[-2] != -sum(data[6:-2]) % 128:
        return 'invalid DX7 checksum'
    return None
