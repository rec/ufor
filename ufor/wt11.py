"""Lossless WT11 voice edit buffers, distinct from TX81Z parameter meanings."""

from __future__ import annotations

from functools import cached_property

from pydantic import Field, ValidationError, field_validator

from . import tx81z
from .base import Model


class WT11Voice(Model):
    """WT11 VCED, including its three-stage pitch envelope."""

    data: bytes = Field(strict=True)

    @field_validator('data')
    @classmethod
    def valid_data(cls, value: bytes) -> bytes:
        if len(value) != 93 or any(x >= 128 for x in value):
            raise ValueError('WT11 VCED data must contain 93 seven-bit bytes')
        return value

    def operator(self, number: int) -> tx81z.TX81ZOperator:
        # WT11 Add-5 chart 1 orders the blocks OP4, OP2, OP3, OP1.
        operator = tx81z.TX81ZVoice(data=self.data).operator(
            5 - number if number in (2, 3) else number
        )
        return operator.model_copy(update={'number': number})

    @cached_property
    def pitch_envelope(self) -> WT11PitchEnvelope:
        return WT11PitchEnvelope(
            rates=list(self.data[87:90]), levels=list(self.data[90:93])
        )

    @cached_property
    def parameter_diagnostic(self) -> str | None:
        if self.data[52] > 7 or self.data[53] > 7:
            return 'WT11 algorithm or feedback is outside 0 through 7'
        for number in range(1, 5):
            try:
                self.operator(number)
            except ValidationError as error:
                return (
                    f'WT11 operator {number} has invalid {error.errors()[0]["loc"][0]}'
                )
        if self.data[75] > 100:
            return 'WT11 breath pitch bias is outside 0 through 100'
        try:
            _ = self.pitch_envelope
        except ValidationError:
            return 'WT11 pitch envelope has a rate or level outside 0 through 99'
        return None


class WT11PitchEnvelope(Model):
    """Raw rates and levels; level 50 is the pitch center."""

    rates: list[int] = Field(min_length=3, max_length=3)
    levels: list[int] = Field(min_length=3, max_length=3)

    @field_validator('rates', 'levels')
    @classmethod
    def valid_parameters(cls, value: list[int]) -> list[int]:
        if any(not 0 <= x <= 99 for x in value):
            raise ValueError('WT11 pitch rates and levels must be from 0 through 99')
        return value


class WT11Additional(Model):
    """WT11 ACED, with the operator order specified by Add-5 chart 2."""

    data: bytes = Field(strict=True)

    @field_validator('data')
    @classmethod
    def valid_data(cls, value: bytes) -> bytes:
        if len(value) != 23 or any(x >= 128 for x in value):
            raise ValueError('WT11 ACED data must contain 23 seven-bit bytes')
        return value

    def operator(self, number: int) -> tx81z.TX81ZAdditionalOperator:
        operator = tx81z.TX81ZAdditional(data=self.data).operator(
            5 - number if number in (2, 3) else number
        )
        return operator.model_copy(update={'number': number})

    @cached_property
    def parameter_diagnostic(self) -> str | None:
        for number in range(1, 5):
            try:
                self.operator(number)
            except ValidationError as error:
                field = error.errors()[0]['loc'][0]
                return f'WT11 additional operator {number} has invalid {field}'
        return None


class WT11Additional2(Model):
    """Raw ACED2 parameters, including all six reserved bytes."""

    data: bytes = Field(strict=True)

    @field_validator('data')
    @classmethod
    def valid_data(cls, value: bytes) -> bytes:
        if len(value) != 10 or any(x >= 128 for x in value):
            raise ValueError('WT11 ACED2 data must contain 10 seven-bit bytes')
        return value

    @cached_property
    def aftertouch(self) -> WT11Aftertouch:
        return WT11Aftertouch(
            pitch=self.data[0],
            amplitude=self.data[1],
            pitch_bias=self.data[2],
            eg_bias=self.data[3],
        )

    @cached_property
    def parameter_diagnostic(self) -> str | None:
        try:
            _ = self.aftertouch
        except ValidationError as error:
            return f'WT11 aftertouch has invalid {error.errors()[0]["loc"][0]}'
        return None


class WT11Aftertouch(Model):
    """WT11 aftertouch assignments; pitch bias is centered at 50."""

    pitch: int = Field(ge=0, le=99, strict=True)
    amplitude: int = Field(ge=0, le=99, strict=True)
    pitch_bias: int = Field(ge=0, le=100, strict=True)
    eg_bias: int = Field(ge=0, le=99, strict=True)


class WT11Entry(Model):
    """One voice message or opaque span, retaining its original byte offset."""

    offset: int = Field(strict=True, ge=0)
    data: bytes = Field(strict=True, min_length=1)

    @cached_property
    def diagnostic(self) -> str | None:
        if self.data[3:6] != bytes([0x7E, 0, 20]):
            diagnostic = tx81z.TX81ZEntry(offset=self.offset, data=self.data).diagnostic
            if diagnostic is not None:
                return diagnostic.replace('TX81Z', 'WT11')
            if self.data[3] == 3 or self.data[6:16] == b'LM  8976AE':
                return None
            return 'unsupported WT11 voice message'
        if self.data[:2] != bytes([0xF0, 0x43]) or self.data[-1] != 0xF7:
            return 'missing WT11 SysEx framing or Yamaha identifier'
        if self.data[2] > 15 or any(x >= 128 for x in self.data[1:-1]):
            return 'unsupported WT11 bulk header or non-seven-bit data'
        if len(self.data) != 28 or self.data[6:16] != b'LM  8023AE':
            return 'unsupported WT11 ACED2 message'
        if self.data[-2] != -sum(self.data[6:-2]) % 128:
            return 'invalid WT11 checksum'
        return None

    @cached_property
    def voice(self) -> WT11Voice | None:
        return (
            WT11Voice(data=self.data[6:-2])
            if self.diagnostic is None and self.data[3] == 3
            else None
        )

    @cached_property
    def additional(self) -> WT11Additional | None:
        return (
            WT11Additional(data=self.data[16:-2])
            if self.diagnostic is None and self.data[6:16] == b'LM  8976AE'
            else None
        )

    @cached_property
    def additional2(self) -> WT11Additional2 | None:
        return (
            WT11Additional2(data=self.data[16:-2])
            if self.diagnostic is None and self.data[6:16] == b'LM  8023AE'
            else None
        )


def parse_wt11(data: bytes) -> list[WT11Entry]:
    """Partition voice dumps without losing malformed or unsupported bytes."""
    return [WT11Entry(offset=x.offset, data=x.data) for x in tx81z.parse_tx81z(data)]
