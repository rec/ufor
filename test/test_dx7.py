import pytest
from pydantic import ValidationError

from ufor.dx7 import DX7FrequencyMode, DX7Voice, parse_dx7


def message(format: int, payload: bytes) -> bytes:
    return (
        bytes([0xF0, 0x43, 0, format, len(payload) >> 7, len(payload) & 127])
        + payload
        + bytes([-sum(payload) % 128, 0xF7])
    )


def test_dx7_parses_single_voice_without_changing_its_data() -> None:
    payload = bytearray(155)
    payload[134] = 31
    payload[135] = 7
    payload[145:155] = b'DX7 VOICE '
    entry = parse_dx7(message(0, bytes(payload)))[0]

    assert entry.diagnostic is None
    assert entry.voices == [DX7Voice(data=bytes(payload))]
    assert entry.voices[0].algorithm == 32
    assert entry.voices[0].feedback == 7
    assert entry.voices[0].title == 'DX7 VOICE '


def test_dx7_parses_all_voices_from_a_packed_bank() -> None:
    payload = bytearray(4096)
    payload[110] = 4
    payload[118:128] = b'FIRST     '
    payload[-18] = 19
    payload[-10:] = b'LAST      '
    entry = parse_dx7(message(9, bytes(payload)))[0]

    assert entry.diagnostic is None
    assert len(entry.voices or []) == 32
    assert entry.voices[0].algorithm == 5
    assert entry.voices[0].title == 'FIRST     '
    assert entry.voices[-1].algorithm == 20
    assert entry.voices[-1].title == 'LAST      '


def test_dx7_decodes_packed_operator_parameters_in_yamaha_order() -> None:
    payload = bytearray(128)
    payload[:17] = bytes(
        [
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            11,
            0b01101110,
            0b00011110,
            13,
            0b00101101,
            15,
            14,
        ]
    )
    operator = DX7Voice(data=bytes(payload)).operator(6)

    assert operator.number == 6
    assert operator.rates == [1, 2, 3, 4]
    assert operator.levels == [5, 6, 7, 8]
    assert operator.left_curve == 2
    assert operator.right_curve == 3
    assert operator.rate_scaling == 6
    assert operator.amplitude_modulation_sensitivity == 2
    assert operator.key_velocity_sensitivity == 7
    assert operator.frequency_mode == DX7FrequencyMode.fixed
    assert operator.coarse == 22
    assert operator.fine == 15
    assert operator.detune == 14


@pytest.mark.parametrize(
    'data,diagnostic',
    [
        (b'bad', 'missing SysEx'),
        (
            bytes([0xF0, 0x43, 0, 1, 0, 0, 0, 0xF7]),
            'unsupported DX7 bulk format',
        ),
        (
            bytes([0xF0, 0x43, 0, 0, 1, 27]) + bytes(155) + bytes([1, 0xF7]),
            'invalid DX7 checksum',
        ),
    ],
)
def test_dx7_preserves_malformed_messages(data: bytes, diagnostic: str) -> None:
    entry = parse_dx7(data)[0]

    assert entry.voices is None
    assert diagnostic in (entry.diagnostic or '')


def test_dx7_voice_rejects_non_portable_storage() -> None:
    with pytest.raises(ValidationError, match='128 or 155'):
        DX7Voice(data=b'bad')
