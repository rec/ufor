"""Lossless WT11 edit buffers, distinct from TX81Z parameter meanings."""

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


class WT11Performance(Model):
    """Raw PCED parameters, including fields the WT11 regards as disabled."""

    data: bytes = Field(strict=True)

    @field_validator('data')
    @classmethod
    def valid_data(cls, value: bytes) -> bytes:
        if len(value) != 110 or any(x >= 128 for x in value):
            raise ValueError('WT11 PCED data must contain 110 seven-bit bytes')
        return value

    def instrument(self, number: int) -> WT11PerformanceInstrument:
        if not 1 <= number <= 8:
            raise ValueError('WT11 instrument number must be from 1 through 8')
        data = self.data[(number - 1) * 12 : number * 12]
        return WT11PerformanceInstrument(
            number=number,
            maximum_notes=data[0],
            voice_number=data[1] * 128 + data[2],
            receive_channel=data[3],
            low_note=data[4],
            high_note=data[5],
            detune=data[6],
            note_shift=data[7],
            volume=data[8],
            output_assign=data[9],
            lfo_select=data[10],
            micro_tune_enable=data[11],
        )

    @cached_property
    def instruments(self) -> list[WT11PerformanceInstrument]:
        return [self.instrument(x) for x in range(1, 9)]

    @cached_property
    def parameter_diagnostic(self) -> str | None:
        for number in range(1, 9):
            try:
                self.instrument(number)
            except ValidationError as error:
                field = error.errors()[0]['loc'][0]
                return f'WT11 instrument {number} has invalid {field}'
        for index, maximum, name in (
            (96, 12, 'micro tune table'),
            (97, 1, 'assign mode'),
            (98, 12, 'effect select'),
            (99, 11, 'micro tune key'),
        ):
            if self.data[index] > maximum:
                return f'WT11 performance has invalid {name}'
        if any(x < 32 for x in self.data[100:110]):
            return 'WT11 performance has invalid title'
        return None

    @property
    def title(self) -> str:
        return self.data[100:110].decode('ascii')


class WT11PerformanceInstrument(tx81z.TX81ZPerformanceInstrument):
    """WT11 wire values; micro-tune enable is stored but regarded as off."""

    voice_number: int = Field(ge=0, le=255, strict=True)


class WT11Performance2(Model):
    """Raw PCED2, including reserved bytes and fixed-on DSP enables."""

    data: bytes = Field(strict=True)

    @field_validator('data')
    @classmethod
    def valid_data(cls, value: bytes) -> bytes:
        if len(value) != 33 or any(x >= 128 for x in value):
            raise ValueError('WT11 PCED2 data must contain 33 seven-bit bytes')
        return value

    @cached_property
    def settings(self) -> WT11PerformanceSettings:
        return WT11PerformanceSettings(
            dsp_select=self.data[16],
            balance=self.data[17],
            time=self.data[20],
            lfo_control=self.data[23],
        )

    @cached_property
    def parameter_diagnostic(self) -> str | None:
        for number in range(1, 9):
            if self.data[number * 2 - 1] != 1:
                return f'WT11 instrument {number} DSP enable must be 1'
        try:
            _ = self.settings
        except ValidationError as error:
            return f'WT11 performance has invalid {error.errors()[0]["loc"][0]}'
        return None


class WT11PerformanceSettings(Model):
    """PCED2 wire values; LFO control 0/1/2 means breath/lip/off."""

    dsp_select: int = Field(ge=0, le=10, strict=True)
    balance: int = Field(ge=0, le=99, strict=True)
    time: int = Field(ge=0, le=36, strict=True)
    lfo_control: int = Field(ge=0, le=2, strict=True)


class WT11VoiceMemory(Model):
    """One packed VMEM voice, retaining its unused bytes and reserved bits."""

    data: bytes = Field(strict=True, min_length=128, max_length=128)

    @field_validator('data')
    @classmethod
    def valid_data(cls, value: bytes) -> bytes:
        if any(x >= 128 for x in value):
            raise ValueError('WT11 VMEM requires seven-bit bytes')
        return value

    @cached_property
    def voice(self) -> WT11Voice:
        data = bytearray(93)
        for index in range(4):
            packed = self.data[index * 10 : index * 10 + 10]
            start = index * 13
            data[start : start + 13] = bytes(
                [
                    packed[0] & 31,
                    packed[1] & 31,
                    packed[2] & 31,
                    packed[3] & 15,
                    packed[4] & 15,
                    packed[5],
                    (packed[9] >> 3) & 3,
                    (packed[6] >> 3) & 7,
                    (packed[6] >> 6) & 1,
                    packed[6] & 7,
                    packed[7],
                    packed[8] & 63,
                    packed[9] & 7,
                ]
            )
        data[52:63] = bytes(
            [
                self.data[40] & 7,
                (self.data[40] >> 3) & 7,
                *self.data[41:45],
                self.data[40] >> 6,
                self.data[45] & 3,
                (self.data[45] >> 4) & 7,
                (self.data[45] >> 2) & 3,
                self.data[46] & 63,
            ]
        )
        data[63:71] = bytes(
            [
                (self.data[48] >> 3) & 1,
                self.data[47] & 15,
                self.data[48] & 1,
                self.data[49],
                self.data[50],
                (self.data[48] >> 2) & 1,
                (self.data[48] >> 1) & 1,
                (self.data[48] >> 4) & 1,
            ]
        )
        data[71:77] = self.data[51:57]
        data[77:87] = self.data[57:67]
        data[87:93] = self.data[67:73]
        return WT11Voice(data=bytes(data))

    @cached_property
    def additional(self) -> WT11Additional:
        data = bytearray(23)
        for index in range(4):
            first, second = self.data[73 + index * 2 : 75 + index * 2]
            data[index * 5 : index * 5 + 5] = bytes(
                [
                    (first >> 3) & 1,
                    first & 7,
                    second & 15,
                    (second >> 4) & 7,
                    (first >> 4) & 3,
                ]
            )
        data[20] = self.data[81] & 7
        data[21:23] = self.data[82:84]
        return WT11Additional(data=bytes(data))

    @cached_property
    def additional2(self) -> WT11Additional2:
        bias = self.data[86]
        if bias > 100:
            raise ValueError(
                'WT11 packed aftertouch pitch bias is outside 0 through 100'
            )
        return WT11Additional2(
            data=bytes(
                [
                    self.data[84],
                    self.data[85],
                    bias + 50 if bias <= 50 else bias - 51,
                    self.data[87],
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                ]
            )
        )


class WT11PerformanceMemory(Model):
    """One packed PMEM allocation with an unpacked PCED view."""

    data: bytes = Field(strict=True, min_length=76, max_length=76)

    @field_validator('data')
    @classmethod
    def valid_data(cls, value: bytes) -> bytes:
        if any(x >= 128 for x in value):
            raise ValueError('WT11 PMEM requires seven-bit bytes')
        return value

    @cached_property
    def performance(self) -> WT11Performance:
        data = bytearray(110)
        for index in range(8):
            packed = self.data[index * 8 : index * 8 + 8]
            data[index * 12 : index * 12 + 12] = bytes(
                [
                    packed[0] & 15,
                    (packed[0] >> 4) & 1,
                    packed[1],
                    packed[2] & 31,
                    packed[3],
                    packed[4],
                    packed[5] & 15,
                    packed[6] & 63,
                    packed[7],
                    (packed[0] >> 5) & 3,
                    (packed[2] >> 5) & 3,
                    packed[6] >> 6,
                ]
            )
        data[96:100] = bytes(
            [
                self.data[64] & 15,
                self.data[65] & 1,
                ((self.data[64] >> 4) & 3) * 4 + ((self.data[65] >> 1) & 3),
                (self.data[65] >> 3) & 15,
            ]
        )
        data[100:110] = self.data[66:76]
        return WT11Performance(data=bytes(data))


class WT11PerformanceMemory2(Model):
    """One PMEM2 record; unlike PCED2, its DSP enables can be off."""

    data: bytes = Field(strict=True, min_length=25, max_length=25)

    @field_validator('data')
    @classmethod
    def valid_data(cls, value: bytes) -> bytes:
        if any(x >= 128 for x in value):
            raise ValueError('WT11 PMEM2 requires seven-bit bytes')
        return value

    @cached_property
    def dsp_enables(self) -> list[bool]:
        return [bool(x & 64) for x in self.data[:8]]

    @cached_property
    def settings(self) -> WT11PerformanceSettings:
        return WT11PerformanceSettings(
            dsp_select=self.data[8],
            balance=self.data[9],
            time=self.data[12],
            lfo_control=self.data[15],
        )


class WT11VoiceBank(Model):
    """Thirty-two packed voices, excluding SysEx framing."""

    data: bytes = Field(strict=True, min_length=4096, max_length=4096)

    @field_validator('data')
    @classmethod
    def valid_data(cls, value: bytes) -> bytes:
        if any(x >= 128 for x in value):
            raise ValueError('WT11 VMEM bank requires seven-bit bytes')
        return value

    @cached_property
    def voices(self) -> list[WT11VoiceMemory]:
        return [
            WT11VoiceMemory(data=self.data[i : i + 128]) for i in range(0, 4096, 128)
        ]


class WT11PerformanceBank(Model):
    """Thirty-two PMEM records, excluding the ten-byte format identifier."""

    data: bytes = Field(strict=True, min_length=2432, max_length=2432)

    @field_validator('data')
    @classmethod
    def valid_data(cls, value: bytes) -> bytes:
        if any(x >= 128 for x in value):
            raise ValueError('WT11 PMEM bank requires seven-bit bytes')
        return value

    @cached_property
    def performances(self) -> list[WT11PerformanceMemory]:
        return [
            WT11PerformanceMemory(data=self.data[i : i + 76])
            for i in range(0, 2432, 76)
        ]


class WT11PerformanceBank2(Model):
    """Thirty-two PMEM2 records, excluding the ten-byte format identifier."""

    data: bytes = Field(strict=True, min_length=800, max_length=800)

    @field_validator('data')
    @classmethod
    def valid_data(cls, value: bytes) -> bytes:
        if any(x >= 128 for x in value):
            raise ValueError('WT11 PMEM2 bank requires seven-bit bytes')
        return value

    @cached_property
    def performances(self) -> list[WT11PerformanceMemory2]:
        return [
            WT11PerformanceMemory2(data=self.data[i : i + 25])
            for i in range(0, 800, 25)
        ]


class WT11Entry(Model):
    """One edit-buffer message or opaque span at its original byte offset."""

    offset: int = Field(strict=True, ge=0)
    data: bytes = Field(strict=True, min_length=1)

    @cached_property
    def diagnostic(self) -> str | None:
        if (
            len(self.data) < 8
            or self.data[:2] != bytes([0xF0, 0x43])
            or self.data[-1] != 0xF7
        ):
            return 'missing WT11 SysEx framing or Yamaha identifier'
        if self.data[2] > 15 or any(x >= 128 for x in self.data[1:-1]):
            return 'unsupported WT11 bulk header or non-seven-bit data'
        if (layout := _BULK_LAYOUTS.get(self.data[3:6])) is None:
            return 'unsupported WT11 bulk format or byte count'
        size, identifier = layout
        if len(self.data) != size or (identifier and self.data[6:16] != identifier):
            return 'unsupported WT11 message length or identifier'
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
            if self.diagnostic is None and self.data[3:6] == bytes([0x7E, 0, 33])
            else None
        )

    @cached_property
    def additional2(self) -> WT11Additional2 | None:
        return (
            WT11Additional2(data=self.data[16:-2])
            if self.diagnostic is None and self.data[3:6] == bytes([0x7E, 0, 20])
            else None
        )

    @cached_property
    def performance(self) -> WT11Performance | None:
        return (
            WT11Performance(data=self.data[16:-2])
            if self.diagnostic is None and self.data[3:6] == bytes([0x7E, 0, 120])
            else None
        )

    @cached_property
    def performance2(self) -> WT11Performance2 | None:
        return (
            WT11Performance2(data=self.data[16:-2])
            if self.diagnostic is None and self.data[3:6] == bytes([0x7E, 0, 43])
            else None
        )

    @cached_property
    def voice_bank(self) -> WT11VoiceBank | None:
        return (
            WT11VoiceBank(data=self.data[6:-2])
            if self.diagnostic is None and self.data[3] == 4
            else None
        )

    @cached_property
    def performance_bank(self) -> WT11PerformanceBank | None:
        return (
            WT11PerformanceBank(data=self.data[16:-2])
            if self.diagnostic is None and self.data[3:6] == bytes([0x7E, 19, 10])
            else None
        )

    @cached_property
    def performance_bank2(self) -> WT11PerformanceBank2 | None:
        return (
            WT11PerformanceBank2(data=self.data[16:-2])
            if self.diagnostic is None and self.data[3:6] == bytes([0x7E, 6, 42])
            else None
        )


def parse_wt11(data: bytes) -> list[WT11Entry]:
    """Partition edit-buffer dumps without losing malformed or unsupported bytes."""
    return [WT11Entry(offset=x.offset, data=x.data) for x in tx81z.parse_tx81z(data)]


_BULK_LAYOUTS = {
    bytes([3, 0, 93]): (101, b''),
    bytes([0x7E, 0, 33]): (41, b'LM  8976AE'),
    bytes([0x7E, 0, 20]): (28, b'LM  8023AE'),
    bytes([0x7E, 0, 120]): (128, b'LM  8976PE'),
    bytes([0x7E, 0, 43]): (51, b'LM  8073PE'),
    bytes([4, 32, 0]): (4104, b''),
    bytes([0x7E, 19, 10]): (2450, b'LM  8976PM'),
    bytes([0x7E, 6, 42]): (818, b'LM  8073PM'),
}
