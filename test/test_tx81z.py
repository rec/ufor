import pytest
from pydantic import ValidationError

from ufor.tx81z import TX81ZAdditional, TX81ZVoice, parse_tx81z


def message(header: bytes, payload: bytes) -> bytes:
    return (
        bytes([0xF0, 0x43, 0]) + header + payload + bytes([-sum(payload) % 128, 0xF7])
    )


def test_tx81z_parses_vced_voice_without_changing_data() -> None:
    payload = bytes(range(93))
    entry = parse_tx81z(message(bytes([3, 0, 93]), payload))[0]

    assert entry.diagnostic is None
    assert entry.voice == TX81ZVoice(data=payload)
    assert entry.additional is None


def test_tx81z_parses_aced_additional_operator_data() -> None:
    payload = b'LM  8976AE' + bytes(range(23))
    entry = parse_tx81z(message(bytes([0x7E, 0, 33]), payload))[0]

    assert entry.diagnostic is None
    assert entry.voice is None
    assert entry.additional == TX81ZAdditional(data=bytes(range(23)))


@pytest.mark.parametrize(
    'data,diagnostic',
    [
        (b'bad', 'missing SysEx'),
        (
            bytes([0xF0, 0x43, 0, 3, 0, 92]) + bytes(92) + bytes([0, 0xF7]),
            'unsupported',
        ),
        (
            bytes([0xF0, 0x43, 0, 3, 0, 93]) + bytes(93) + bytes([1, 0xF7]),
            'invalid TX81Z checksum',
        ),
    ],
)
def test_tx81z_preserves_malformed_messages(data: bytes, diagnostic: str) -> None:
    entry = parse_tx81z(data)[0]

    assert entry.voice is None
    assert entry.additional is None
    assert diagnostic in (entry.diagnostic or '')


def test_tx81z_payloads_reject_other_shapes() -> None:
    with pytest.raises(ValidationError, match='93 seven-bit'):
        TX81ZVoice(data=bytes(92))
    with pytest.raises(ValidationError, match='23 seven-bit'):
        TX81ZAdditional(data=bytes(22))
