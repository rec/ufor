import pytest
from pydantic import ValidationError
from test_tx81z import message

from ufor import tx81z, wt11


def test_wt11_decodes_its_operator_order_and_pitch_envelope() -> None:
    data = bytearray(93)
    additional = bytearray(23)
    for index, number in enumerate([4, 2, 3, 1]):
        data[index * 13] = number
        additional[index * 5 + 3] = number
    data[75] = 100
    data[87:93] = bytes([0, 50, 99, 99, 50, 0])
    data[77:87] = b'WT11 TEST '
    voice_entry, additional_entry = wt11.parse_wt11(
        message(bytes([3, 0, 93]), bytes(data))
        + message(bytes([0x7E, 0, 33]), b'LM  8976AE' + additional)
    )
    voice = voice_entry.voice
    extension = additional_entry.additional
    assert voice_entry.diagnostic is None
    assert additional_entry.diagnostic is None
    assert voice is not None and extension is not None
    assert voice.parameter_diagnostic is None
    assert voice.data == data
    assert extension.data == additional
    for number in range(1, 5):
        assert voice.operator(number).number == number
        assert voice.operator(number).attack_rate == number
        assert extension.operator(number).number == number
        assert extension.operator(number).waveform == number
    assert voice.pitch_envelope.rates == [0, 50, 99]
    assert voice.pitch_envelope.levels == [99, 50, 0]
    # The same wire blocks keep their existing TX81Z interpretation.
    assert tx81z.TX81ZVoice(data=bytes(data)).operator(2).attack_rate == 3
    assert tx81z.TX81ZAdditional(data=bytes(additional)).operator(2).waveform == 3


@pytest.mark.parametrize('bias', [0, 50, 100])
def test_wt11_retains_aftertouch_assignments_and_reserved_bytes(bias: int) -> None:
    data = bytes([99, 0, bias, 99, 1, 2, 3, 4, 5, 127])
    raw = message(bytes([0x7E, 0, 20]), b'LM  8023AE' + data)
    entry = wt11.parse_wt11(raw)[0]
    assert entry.diagnostic is None
    assert entry.voice is None
    assert entry.additional is None
    extension = entry.additional2
    assert extension is not None
    assert extension.parameter_diagnostic is None
    assert extension.data == data
    assert extension.aftertouch.pitch == 99
    assert extension.aftertouch.amplitude == 0
    assert extension.aftertouch.pitch_bias == bias
    assert extension.aftertouch.eg_bias == 99
    assert wt11.WT11Entry.model_validate(entry.model_dump()).data == raw
    assert tx81z.parse_tx81z(raw)[0].diagnostic is not None


@pytest.mark.parametrize('index', [75, 87, 88, 89, 90, 91, 92])
def test_wt11_retains_invalid_voice_parameters_with_diagnostics(index: int) -> None:
    data = bytearray(93)
    data[index] = 101 if index == 75 else 100
    entry = wt11.parse_wt11(message(bytes([3, 0, 93]), bytes(data)))[0]
    assert entry.diagnostic is None
    assert entry.voice is not None
    assert entry.voice.data == data
    assert entry.voice.parameter_diagnostic is not None


@pytest.mark.parametrize('index', range(4))
def test_wt11_retains_invalid_aftertouch_parameters_with_diagnostics(
    index: int,
) -> None:
    data = bytearray(10)
    data[index] = 101 if index == 2 else 100
    entry = wt11.parse_wt11(message(bytes([0x7E, 0, 20]), b'LM  8023AE' + data))[0]
    assert entry.diagnostic is None
    assert entry.additional2 is not None
    assert entry.additional2.data == data
    assert entry.additional2.parameter_diagnostic is not None
    with pytest.raises(ValidationError):
        _ = entry.additional2.aftertouch


@pytest.mark.parametrize(
    'fault', ['length', 'identifier', 'checksum', 'device', 'seven-bit']
)
def test_wt11_preserves_malformed_messages_and_opaque_bytes(fault: str) -> None:
    raw = bytearray(message(bytes([0x7E, 0, 20]), b'LM  8023AE' + bytes(10)))
    if fault == 'length':
        del raw[20]
    elif fault == 'identifier':
        raw[15] ^= 1
    elif fault == 'checksum':
        raw[-2] ^= 1
    elif fault == 'device':
        raw[2] = 16
    else:
        raw[20] = 128
    entries = wt11.parse_wt11(b'opaque' + raw + b'\xf0\x43')
    assert b''.join(x.data for x in entries) == b'opaque' + raw + b'\xf0\x43'
    assert entries[1].offset == 6
    for entry in entries:
        assert entry.diagnostic is not None
        assert entry.voice is None
        assert entry.additional is None
        assert entry.additional2 is None


@pytest.mark.parametrize('data', [bytes(9), bytes(11), bytes([128]) + bytes(9)])
def test_wt11_rejects_invalid_additional_buffer_shapes(data: bytes) -> None:
    with pytest.raises(ValidationError, match='10 seven-bit bytes'):
        wt11.WT11Additional2(data=data)


def test_wt11_keeps_performance_dumps_opaque_until_supported() -> None:
    raw = message(bytes([0x7E, 0, 120]), b'LM  8976PE' + bytes(110))
    entry = wt11.parse_wt11(raw)[0]
    assert entry.data == raw
    assert entry.diagnostic == 'unsupported WT11 voice message'
    assert entry.voice is None
    assert entry.additional is None
    assert entry.additional2 is None


def test_wt11_reads_the_documented_centered_aftertouch_message() -> None:
    raw = bytes.fromhex('f043007e00144c4d20203830323341450000320000000000000022f7')
    entry = wt11.parse_wt11(raw)[0]
    assert entry.diagnostic is None
    assert entry.additional2 is not None
    assert entry.additional2.aftertouch.pitch_bias == 50
    assert entry.additional2.aftertouch.pitch == 0
    assert entry.additional2.aftertouch.amplitude == 0
    assert entry.additional2.aftertouch.eg_bias == 0
