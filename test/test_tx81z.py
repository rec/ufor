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


def test_tx81z_decodes_paired_operator_parameters() -> None:
    voice_data = bytearray(93)
    voice_data[:13] = bytes([1, 2, 3, 4, 5, 6, 3, 7, 1, 7, 10, 11, 6])
    voice_data[52] = 7
    voice_data[53] = 6
    voice_data[77:87] = b'TX81Z TEST'
    additional_data = bytearray(23)
    additional_data[:5] = bytes([1, 7, 15, 6, 3])
    voice = TX81ZVoice(data=bytes(voice_data))
    additional = TX81ZAdditional(data=bytes(additional_data))

    operator = voice.operator(4)
    extension = additional.operator(4)

    assert operator.attack_rate == 1
    assert operator.amplitude_modulation_enable is True
    assert operator.detune == 6
    assert extension.fixed_frequency is True
    assert extension.fixed_frequency_range == 7
    assert extension.waveform == 6
    assert extension.eg_shift == 3
    assert voice.algorithm == 8
    assert voice.feedback == 6
    assert voice.title == 'TX81Z TEST'


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


def test_tx81z_reports_invalid_parameters_without_losing_raw_payloads() -> None:
    payload = bytearray(93)
    payload[52] = 127
    entry = parse_tx81z(message(bytes([3, 0, 93]), bytes(payload)))[0]

    assert entry.diagnostic is None
    assert entry.voice.data == bytes(payload)
    assert entry.voice.parameter_diagnostic == (
        'TX81Z algorithm 128 is outside 1 through 8'
    )

    payload[52] = 0
    payload[0] = 127
    assert 'operator 4 has invalid attack_rate' in (
        TX81ZVoice(data=bytes(payload)).parameter_diagnostic or ''
    )
    additional = bytearray(23)
    additional[1] = 127
    assert 'additional operator 4 has invalid fixed_frequency_range' in (
        TX81ZAdditional(data=bytes(additional)).parameter_diagnostic or ''
    )
