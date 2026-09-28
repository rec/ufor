import pytest
from pydantic import ValidationError

from ufor.dx7 import DX7Voice, parse_dx7


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
