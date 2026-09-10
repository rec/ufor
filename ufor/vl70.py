"""Lossless VL70m dump inspection and relocation, without file or device access."""

from functools import cached_property

from pydantic import Field, field_validator

from .base import Model


class VL70Patch(Model):
    """One validated message in the observed 174-byte native bulk family."""

    data: bytes = Field(strict=True)

    @field_validator('data')
    @classmethod
    def valid_message(cls, value: bytes) -> bytes:
        if problem := _diagnostic(value):
            raise ValueError(problem)
        return value

    @property
    def title(self) -> str:
        """The eight ASCII title bytes, including spaces and control characters."""
        return self.data[9:17].decode('ascii')

    @property
    def slot(self) -> int:
        return self.data[8]

    @property
    def device_number(self) -> int:
        return self.data[2]

    def relocate(self, slot: int, device_number: int | None = None) -> 'VL70Patch':
        """Return an independent patch; never alter or repair the original."""
        if type(slot) is not int or not 0 <= slot <= 63:
            raise ValueError('slot must be an integer in 0–63')
        if device_number is not None and (
            type(device_number) is not int or not 0 <= device_number <= 15
        ):
            raise ValueError('device number must be an integer in 0–15')
        data = bytearray(self.data)
        data[8] = slot
        if device_number is not None:
            data[2] = device_number
        data[172] = -sum(data[4:172]) % 128
        return VL70Patch(data=bytes(data))


class VL70Entry(Model):
    """A message or opaque span at its original byte offset in a dump."""

    offset: int = Field(strict=True, ge=0)
    data: bytes = Field(strict=True, min_length=1)

    @cached_property
    def diagnostic(self) -> str | None:
        """Why this span cannot be relocated, or None for an editable patch."""
        return _diagnostic(self.data)

    @cached_property
    def patch(self) -> VL70Patch | None:
        return None if self.diagnostic else VL70Patch(data=self.data)


def parse_vl70(data: bytes) -> list[VL70Entry]:
    """Partition a dump without losing bytes, duplicates or malformed material.

    A new F0 resynchronizes after an unterminated message. Bytes outside messages
    remain opaque entries. Joining entry.data reproduces the exact input.
    """
    entries: list[VL70Entry] = []
    start = 0
    for index, value in enumerate(data):
        if value == 0xF0 and index > start:
            entries.append(VL70Entry(offset=start, data=data[start:index]))
            start = index
        elif value == 0xF7:
            entries.append(VL70Entry(offset=start, data=data[start : index + 1]))
            start = index + 1
    if start < len(data):
        entries.append(VL70Entry(offset=start, data=data[start:]))
    return entries


def _diagnostic(data: bytes) -> str | None:
    if not data or data[0] != 0xF0 or data[-1] != 0xF7:
        return 'missing SysEx framing (F0 ... F7)'
    if any(i >= 128 for i in data[1:-1]):
        return 'SysEx interior contains non-seven-bit data'
    if len(data) != 174:
        return 'unsupported message length: expected 174 bytes'
    if data[1] != 0x43 or data[3] != 0x57 or data[2] > 15:
        return 'unsupported Yamaha VL70m bulk header'
    if (data[4] << 7) + data[5] != 163:
        return 'payload byte count must be 163'
    if data[6:8] != b'\x40\x00':
        return 'unsupported VL70m address family'
    if data[8] > 63:
        return 'source slot is outside the supported range 0–63'
    if sum(data[4:173]) % 128:
        return 'invalid VL70m checksum'
    return None
