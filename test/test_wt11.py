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


def test_wt11_keeps_unknown_bulk_byte_counts_opaque() -> None:
    raw = message(bytes([4, 0, 1]), bytes(1))
    entry = wt11.parse_wt11(raw)[0]
    assert entry.data == raw
    assert entry.diagnostic is not None
    assert entry.voice is None
    assert entry.additional is None
    assert entry.additional2 is None
    assert entry.performance is None
    assert entry.performance2 is None


def test_wt11_reads_the_documented_centered_aftertouch_message() -> None:
    raw = bytes.fromhex('f043007e00144c4d20203830323341450000320000000000000022f7')
    entry = wt11.parse_wt11(raw)[0]
    assert entry.diagnostic is None
    assert entry.additional2 is not None
    assert entry.additional2.aftertouch.pitch_bias == 50
    assert entry.additional2.aftertouch.pitch == 0
    assert entry.additional2.aftertouch.amplitude == 0
    assert entry.additional2.aftertouch.eg_bias == 0


def performance_data() -> bytes:
    data = bytearray(110)
    for index in range(8):
        data[index * 12 : index * 12 + 12] = bytes(
            [index, 1, 72 + index, 16, index, 127, 7, 24, 99, 3, index % 4, 1]
        )
    data[96:100] = bytes([12, 1, 12, 11])
    data[100:110] = b'WT11 PERFM'
    return bytes(data)


def performance2_data() -> bytes:
    data = bytearray(range(33))
    data[1:16:2] = bytes([1] * 8)
    data[16], data[17], data[20], data[23] = 10, 99, 36, 2
    return bytes(data)


def test_wt11_decodes_paired_performance_buffers_without_changing_bytes() -> None:
    data = performance_data()
    extra = performance2_data()
    raw = message(bytes([0x7E, 0, 120]), b'LM  8976PE' + data)
    raw2 = message(bytes([0x7E, 0, 43]), b'LM  8073PE' + extra)
    entries = wt11.parse_wt11(raw + raw2)
    assert entries[1].offset == len(raw)
    assert b''.join(x.data for x in entries) == raw + raw2
    performance = entries[0].performance
    extension = entries[1].performance2
    assert performance is not None and extension is not None
    assert entries[0].diagnostic is None
    assert entries[1].diagnostic is None
    assert entries[0].performance2 is None
    assert entries[1].performance is None
    for entry in entries:
        assert entry.voice is None
        assert entry.additional is None
        assert entry.additional2 is None
    assert performance.data == data
    assert performance.title == 'WT11 PERFM'
    assert performance.parameter_diagnostic is None
    for number, instrument in enumerate(performance.instruments, 1):
        assert instrument.number == number
        assert instrument.maximum_notes == number - 1
        assert instrument.voice_number == 199 + number
        assert instrument.receive_channel == 16
        assert instrument.low_note == number - 1
        assert instrument.high_note == 127
        assert instrument.detune == 7
        assert instrument.note_shift == 24
        assert instrument.volume == 99
        assert instrument.output_assign == 3
        assert instrument.lfo_select == (number - 1) % 4
        assert instrument.micro_tune_enable == 1
    assert extension.data == extra
    assert extension.parameter_diagnostic is None
    assert extension.settings.dsp_select == 10
    assert extension.settings.balance == 99
    assert extension.settings.time == 36
    assert extension.settings.lfo_control == 2


@pytest.mark.parametrize('index', [0, 1, 3, 6, 7, 8, 9, 10, 11, 96, 97, 98, 99, 100])
def test_wt11_preserves_invalid_performance_parameters(index: int) -> None:
    data = bytearray(performance_data())
    data[index] = 0 if index == 100 else 127
    entry = wt11.parse_wt11(message(bytes([0x7E, 0, 120]), b'LM  8976PE' + data))[0]
    assert entry.diagnostic is None
    assert entry.performance is not None
    assert entry.performance.data == data
    assert entry.performance.parameter_diagnostic is not None


@pytest.mark.parametrize('index', [1, 3, 5, 7, 9, 11, 13, 15, 16, 17, 20, 23])
def test_wt11_preserves_invalid_performance_extension_parameters(index: int) -> None:
    data = bytearray(performance2_data())
    data[index] = 127
    entry = wt11.parse_wt11(message(bytes([0x7E, 0, 43]), b'LM  8073PE' + data))[0]
    assert entry.diagnostic is None
    assert entry.performance2 is not None
    assert entry.performance2.data == data
    assert entry.performance2.parameter_diagnostic is not None


@pytest.mark.parametrize('identifier', [b'LM  8976PE', b'LM  8073PE'])
@pytest.mark.parametrize(
    'fault', ['length', 'identifier', 'checksum', 'device', 'seven-bit']
)
def test_wt11_preserves_malformed_performance_messages(
    identifier: bytes, fault: str
) -> None:
    data = performance_data() if identifier == b'LM  8976PE' else performance2_data()
    raw = bytearray(message(bytes([0x7E, 0, len(data) + 10]), identifier + data))
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
    entry = wt11.parse_wt11(bytes(raw))[0]
    assert entry.data == raw
    assert entry.diagnostic is not None
    assert entry.performance is None
    assert entry.performance2 is None


@pytest.mark.parametrize('number', [0, 9])
def test_wt11_rejects_instrument_numbers_outside_the_performance(number: int) -> None:
    performance = wt11.WT11Performance(data=performance_data())
    with pytest.raises(ValueError, match='1 through 8'):
        performance.instrument(number)


@pytest.mark.parametrize('length', [109, 111, 32, 34])
def test_wt11_rejects_incorrect_performance_buffer_shapes(length: int) -> None:
    model = wt11.WT11Performance if length > 100 else wt11.WT11Performance2
    with pytest.raises(ValidationError, match='seven-bit bytes'):
        model(data=bytes(length))
