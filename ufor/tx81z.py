"""Lossless TX81Z voice-dump inspection, including additional operator data."""

from __future__ import annotations

from functools import cached_property

from pydantic import Field, ValidationError, field_validator

from .base import Model


class TX81ZVoice(Model):
    """One structurally valid raw TX81Z VCED payload; parameters may not decode."""

    data: bytes = Field(strict=True)

    @field_validator('data')
    @classmethod
    def valid_data(cls, value: bytes) -> bytes:
        if len(value) != 93 or any(byte >= 128 for byte in value):
            raise ValueError('TX81Z VCED data must contain 93 seven-bit bytes')
        return value

    @cached_property
    def parameter_diagnostic(self) -> str | None:
        """Why a supported parameter cannot be decoded from the raw bytes."""
        if not 1 <= self.algorithm <= 8:
            return f'TX81Z algorithm {self.algorithm} is outside 1 through 8'
        if not 0 <= self.feedback <= 7:
            return f'TX81Z feedback {self.feedback} is outside 0 through 7'
        for number in range(1, 5):
            try:
                self.operator(number)
            except ValidationError as error:
                field = error.errors()[0]['loc'][0]
                return f'TX81Z operator {number} has invalid {field}'
        return None

    @cached_property
    def operators(self) -> list[TX81ZOperator]:
        return [self.operator(number) for number in range(1, 5)]

    def operator(self, number: int) -> TX81ZOperator:
        if not 1 <= number <= 4:
            raise ValueError('TX81Z operator number must be from 1 through 4')
        start = (4 - number) * 13
        data = self.data[start : start + 13]
        return TX81ZOperator(
            number=number,
            attack_rate=data[0],
            decay_1_rate=data[1],
            decay_2_rate=data[2],
            release_rate=data[3],
            decay_1_level=data[4],
            level_scaling=data[5],
            rate_scaling=data[6],
            eg_bias_sensitivity=data[7],
            amplitude_modulation_enable=bool(data[8]),
            key_velocity_sensitivity=data[9],
            output_level=data[10],
            coarse=data[11],
            detune=data[12],
        )

    @property
    def algorithm(self) -> int:
        return self.data[52] + 1

    @property
    def feedback(self) -> int:
        return self.data[53]

    @property
    def title(self) -> str:
        return self.data[77:87].decode('ascii')


class TX81ZOperator(Model):
    """One TX81Z VCED operator, numbered as on the front panel."""

    number: int = Field(ge=1, le=4, strict=True)
    attack_rate: int = Field(ge=0, le=31, strict=True)
    decay_1_rate: int = Field(ge=0, le=31, strict=True)
    decay_2_rate: int = Field(ge=0, le=31, strict=True)
    release_rate: int = Field(ge=0, le=15, strict=True)
    decay_1_level: int = Field(ge=0, le=15, strict=True)
    level_scaling: int = Field(ge=0, le=99, strict=True)
    rate_scaling: int = Field(ge=0, le=3, strict=True)
    eg_bias_sensitivity: int = Field(ge=0, le=7, strict=True)
    amplitude_modulation_enable: bool
    key_velocity_sensitivity: int = Field(ge=0, le=7, strict=True)
    output_level: int = Field(ge=0, le=99, strict=True)
    coarse: int = Field(ge=0, le=63, strict=True)
    detune: int = Field(ge=0, le=6, strict=True)


class TX81ZAdditional(Model):
    """One structurally valid raw TX81Z ACED payload, including waveforms."""

    data: bytes = Field(strict=True)

    @field_validator('data')
    @classmethod
    def valid_data(cls, value: bytes) -> bytes:
        if len(value) != 23 or any(byte >= 128 for byte in value):
            raise ValueError('TX81Z ACED data must contain 23 seven-bit bytes')
        return value

    @cached_property
    def parameter_diagnostic(self) -> str | None:
        """Why a supported operator extension cannot be decoded."""
        for number in range(1, 5):
            try:
                self.operator(number)
            except ValidationError as error:
                field = error.errors()[0]['loc'][0]
                return f'TX81Z additional operator {number} has invalid {field}'
        return None

    @cached_property
    def operators(self) -> list[TX81ZAdditionalOperator]:
        return [self.operator(number) for number in range(1, 5)]

    def operator(self, number: int) -> TX81ZAdditionalOperator:
        if not 1 <= number <= 4:
            raise ValueError('TX81Z operator number must be from 1 through 4')
        start = (4 - number) * 5
        data = self.data[start : start + 5]
        return TX81ZAdditionalOperator(
            number=number,
            fixed_frequency=bool(data[0]),
            fixed_frequency_range=data[1],
            fine=data[2],
            waveform=data[3],
            eg_shift=data[4],
        )


class TX81ZAdditionalOperator(Model):
    """One TX81Z ACED operator extension, including its waveform choice."""

    number: int = Field(ge=1, le=4, strict=True)
    fixed_frequency: bool
    fixed_frequency_range: int = Field(ge=0, le=7, strict=True)
    fine: int = Field(ge=0, le=15, strict=True)
    waveform: int = Field(ge=0, le=7, strict=True)
    eg_shift: int = Field(ge=0, le=3, strict=True)


class TX81ZEntry(Model):
    """One complete message or opaque span at its original byte offset."""

    offset: int = Field(strict=True, ge=0)
    data: bytes = Field(strict=True, min_length=1)

    @cached_property
    def diagnostic(self) -> str | None:
        """Why the message framing or checksum is invalid; not parameter validity."""
        return _diagnostic(self.data)

    @cached_property
    def voice(self) -> TX81ZVoice | None:
        """Raw VCED payload, or None for ACED and unsupported entries."""
        return (
            TX81ZVoice(data=self.data[6:-2])
            if self.diagnostic is None and self.data[3] == 3
            else None
        )

    @cached_property
    def additional(self) -> TX81ZAdditional | None:
        """Raw ACED payload, or None for VCED and unsupported entries."""
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
