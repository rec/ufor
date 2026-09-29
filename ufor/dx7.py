"""Lossless DX7 voice-dump inspection, without synthesis or device access."""

from enum import StrEnum
from functools import cached_property

from pydantic import Field, field_validator

from .base import Model


class DX7FrequencyMode(StrEnum):
    ratio = 'ratio'
    fixed = 'fixed'


class DX7Operator(Model):
    """One DX7 operator decoded from the stored VCED parameter bytes."""

    number: int = Field(ge=1, le=6, strict=True)
    rates: list[int] = Field(min_length=4, max_length=4)
    levels: list[int] = Field(min_length=4, max_length=4)
    breakpoint: int = Field(ge=0, le=99, strict=True)
    left_depth: int = Field(ge=0, le=99, strict=True)
    right_depth: int = Field(ge=0, le=99, strict=True)
    left_curve: int = Field(ge=0, le=3, strict=True)
    right_curve: int = Field(ge=0, le=3, strict=True)
    rate_scaling: int = Field(ge=0, le=7, strict=True)
    amplitude_modulation_sensitivity: int = Field(ge=0, le=3, strict=True)
    key_velocity_sensitivity: int = Field(ge=0, le=7, strict=True)
    output_level: int = Field(ge=0, le=99, strict=True)
    frequency_mode: DX7FrequencyMode
    coarse: int = Field(ge=0, le=31, strict=True)
    fine: int = Field(ge=0, le=99, strict=True)
    detune: int = Field(ge=0, le=14, strict=True)


class DX7Edge(Model):
    source: int = Field(ge=1, le=6, strict=True)
    destination: int = Field(ge=1, le=6, strict=True)


class DX7Algorithm(Model):
    """One Yamaha DX7 topology, using visible operator numbering."""

    number: int = Field(ge=1, le=32, strict=True)
    edges: list[DX7Edge]
    carriers: list[int] = Field(min_length=1)
    feedback: int = Field(ge=1, le=6, strict=True)


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

    @cached_property
    def operators(self) -> list[DX7Operator]:
        """Operators in Yamaha's visible order, OP1 through OP6."""
        return [self.operator(number) for number in range(1, 7)]

    def operator(self, number: int) -> DX7Operator:
        """Decode one operator while retaining the original packed bytes unchanged."""
        if not 1 <= number <= 6:
            raise ValueError('DX7 operator number must be from 1 through 6')
        if self.packed:
            start = (6 - number) * 17
            data = self.data[start : start + 17]
            curves = data[11]
            sensitivities = data[12]
            mode = data[14]
            return DX7Operator(
                number=number,
                rates=list(data[:4]),
                levels=list(data[4:8]),
                breakpoint=data[8],
                left_depth=data[9],
                right_depth=data[10],
                left_curve=curves & 3,
                right_curve=(curves >> 2) & 3,
                rate_scaling=(curves >> 4) & 7,
                amplitude_modulation_sensitivity=sensitivities & 3,
                key_velocity_sensitivity=(sensitivities >> 2) & 7,
                output_level=data[13],
                frequency_mode=(
                    DX7FrequencyMode.fixed if mode & 1 else DX7FrequencyMode.ratio
                ),
                coarse=(mode >> 1) & 31,
                fine=data[15],
                detune=data[16],
            )
        start = (6 - number) * 21
        data = self.data[start : start + 21]
        return DX7Operator(
            number=number,
            rates=list(data[:4]),
            levels=list(data[4:8]),
            breakpoint=data[8],
            left_depth=data[9],
            right_depth=data[10],
            left_curve=data[11],
            right_curve=data[12],
            rate_scaling=data[13],
            amplitude_modulation_sensitivity=data[14],
            key_velocity_sensitivity=data[15],
            output_level=data[16],
            frequency_mode=(
                DX7FrequencyMode.fixed if data[17] else DX7FrequencyMode.ratio
            ),
            coarse=data[18],
            fine=data[19],
            detune=data[20],
        )

    @cached_property
    def topology(self) -> DX7Algorithm:
        return dx7_algorithm(self.algorithm)


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


def dx7_algorithm(number: int) -> DX7Algorithm:
    """Return the official DX7 routing, with a one-sample delayed feedback tap."""
    if not 1 <= number <= len(DX7_ALGORITHMS):
        raise ValueError('DX7 algorithm must be from 1 through 32')
    edges, carriers, feedback = DX7_ALGORITHMS[number - 1]
    return DX7Algorithm(
        number=number,
        edges=[
            DX7Edge(source=source, destination=destination)
            for source, destination in edges
        ],
        carriers=list(carriers),
        feedback=feedback,
    )


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


DX7_ALGORITHMS = [
    ([(2, 1), (6, 5), (5, 4), (4, 3)], [1, 3], 6),
    ([(2, 1), (6, 5), (5, 4), (4, 3)], [1, 3], 2),
    ([(3, 2), (2, 1), (6, 5), (5, 4)], [1, 4], 6),
    ([(3, 2), (2, 1), (6, 5), (5, 4)], [1, 4], 4),
    ([(2, 1), (4, 3), (6, 5)], [1, 3, 5], 6),
    ([(2, 1), (4, 3), (6, 5)], [1, 3, 5], 5),
    ([(2, 1), (4, 3), (6, 5), (5, 3)], [1, 3], 6),
    ([(2, 1), (4, 3), (6, 5), (5, 3)], [1, 3], 4),
    ([(2, 1), (4, 3), (6, 5), (5, 3)], [1, 3], 2),
    ([(5, 4), (6, 4), (3, 2), (2, 1)], [1, 4], 3),
    ([(5, 4), (6, 4), (3, 2), (2, 1)], [1, 4], 6),
    ([(4, 3), (5, 3), (6, 3), (2, 1)], [1, 3], 2),
    ([(4, 3), (5, 3), (6, 3), (2, 1)], [1, 3], 6),
    ([(2, 1), (5, 4), (6, 4), (4, 3)], [1, 3], 6),
    ([(2, 1), (5, 4), (6, 4), (4, 3)], [1, 3], 2),
    ([(2, 1), (4, 3), (6, 5), (3, 1), (5, 1)], [1], 6),
    ([(2, 1), (4, 3), (6, 5), (3, 1), (5, 1)], [1], 2),
    ([(2, 1), (3, 1), (6, 5), (5, 4), (4, 1)], [1], 3),
    ([(3, 2), (2, 1), (6, 4), (6, 5)], [1, 4, 5], 6),
    ([(3, 1), (3, 2), (5, 4), (6, 4)], [1, 2, 4], 3),
    ([(3, 1), (3, 2), (6, 4), (6, 5)], [1, 2, 4, 5], 3),
    ([(2, 1), (6, 3), (6, 4), (6, 5)], [1, 3, 4, 5], 6),
    ([(3, 2), (2, 1), (6, 4), (6, 5)], [1, 4, 5], 6),
    ([(6, 3), (6, 4), (6, 5)], [1, 2, 3, 4, 5], 6),
    ([(6, 4), (6, 5)], [1, 2, 3, 4, 5], 6),
    ([(3, 2), (5, 4), (6, 4)], [1, 2, 4], 6),
    ([(3, 2), (5, 4), (6, 4)], [1, 2, 4], 3),
    ([(2, 1), (5, 4), (4, 3)], [1, 3, 6], 5),
    ([(4, 3), (6, 5)], [1, 2, 3, 5], 6),
    ([(5, 4), (4, 3)], [1, 2, 3, 6], 5),
    ([(6, 5)], [1, 2, 3, 4, 5], 6),
    ([], [1, 2, 3, 4, 5, 6], 6),
]
