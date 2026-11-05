import pytest
from pydantic import ValidationError
from test_tx81z import message

from ufor import wt11
from ufor.base import Model


def voice_memory(bias: int = 50) -> bytes:
    data = bytearray(128)
    for index, number in enumerate([4, 2, 3, 1]):
        data[index * 10 : index * 10 + 10] = bytes(
            [
                number,
                number + 1,
                number + 2,
                number + 3,
                number + 4,
                50 + number,
                (number % 2) * 64 + number * 8 + 7 - number,
                80 + number,
                number * 5,
                (number % 4) * 8 + number + 1,
            ]
        )
        data[73 + index * 2 : 75 + index * 2] = bytes(
            [
                (number % 4) * 16 + (number % 2) * 8 + 7 - number,
                number * 16 + 11 - number,
            ]
        )
    data[40:57] = bytes(
        [109, 9, 8, 7, 6, 107, 24, 12, 21, 64, 25, 11, 22, 33, 44, 100, 55]
    )
    data[57:67] = b'WT11 VMEM '
    data[67:73] = bytes([3, 40, 99, 0, 50, 99])
    data[81:88] = bytes([7, 23, 45, 99, 88, bias, 77])
    data[88:] = bytes(range(40))
    return bytes(data)


def performance_memory() -> bytes:
    data = bytearray(76)
    for index in range(8):
        data[index * 8 : index * 8 + 8] = bytes(
            [
                (index % 4) * 32 + 16 + index + 1,
                72 + index,
                (index % 4) * 32 + 16,
                index,
                127,
                7 + index,
                (index % 2) * 64 + 24 + index,
                99 - index,
            ]
        )
    data[64:66] = bytes([60, 89])
    data[66:76] = b'WT11 PMEM '
    return bytes(data)


def performance_memory2() -> bytes:
    data = bytearray(range(25))
    for index in range(8):
        data[index] = (index % 2) * 64 + index + 1
    data[8], data[9], data[12], data[15] = 10, 99, 36, 2
    return bytes(data)


@pytest.mark.parametrize(
    'packed_bias,edit_bias', [(0, 50), (49, 99), (50, 100), (51, 0), (100, 49)]
)
def test_wt11_unpacks_vmem_operators_controls_and_aftertouch(
    packed_bias: int, edit_bias: int
) -> None:
    packed = wt11.WT11VoiceMemory(data=voice_memory(packed_bias))
    voice = packed.voice
    additional = packed.additional
    assert voice.parameter_diagnostic is None
    assert additional.parameter_diagnostic is None
    assert packed.additional2.parameter_diagnostic is None
    for number in range(1, 5):
        operator = voice.operator(number)
        extension = additional.operator(number)
        assert operator.attack_rate == number
        assert operator.decay_1_rate == number + 1
        assert operator.decay_2_rate == number + 2
        assert operator.release_rate == number + 3
        assert operator.decay_1_level == number + 4
        assert operator.level_scaling == 50 + number
        assert operator.rate_scaling == number % 4
        assert operator.eg_bias_sensitivity == number
        assert operator.amplitude_modulation_enable == bool(number % 2)
        assert operator.key_velocity_sensitivity == 7 - number
        assert operator.output_level == 80 + number
        assert operator.coarse == number * 5
        assert operator.detune == number + 1
        assert extension.fixed_frequency == bool(number % 2)
        assert extension.fixed_frequency_range == 7 - number
        assert extension.fine == 11 - number
        assert extension.waveform == number
        assert extension.eg_shift == number % 4
    assert voice.data[52] == 5
    assert voice.data[53] == 5
    assert voice.data[54:58] == bytes([9, 8, 7, 6])
    assert voice.data[58] == 1
    assert voice.data[59] == 3
    assert voice.data[60] == 6
    assert voice.data[61] == 2
    assert voice.data[62] == 24
    assert voice.data[63] == 0
    assert voice.data[64] == 12
    assert voice.data[65] == 1
    assert voice.data[66] == 64
    assert voice.data[67] == 25
    assert voice.data[68] == 1
    assert voice.data[69] == 0
    assert voice.data[70] == 1
    assert voice.data[71:77] == bytes([11, 22, 33, 44, 100, 55])
    assert voice.data[77:87] == b'WT11 VMEM '
    assert voice.pitch_envelope.rates == [3, 40, 99]
    assert voice.pitch_envelope.levels == [0, 50, 99]
    assert additional.data[20:23] == bytes([7, 23, 45])
    assert packed.additional2.aftertouch.pitch == 99
    assert packed.additional2.aftertouch.amplitude == 88
    assert packed.additional2.aftertouch.pitch_bias == edit_bias
    assert packed.additional2.aftertouch.eg_bias == 77
    assert packed.data == voice_memory(packed_bias)


def test_wt11_unpacks_performance_bitfields_without_losing_wire_values() -> None:
    packed = wt11.WT11PerformanceMemory(data=performance_memory())
    performance = packed.performance
    assert performance.parameter_diagnostic is None
    for index, instrument in enumerate(performance.instruments):
        assert instrument.number == index + 1
        assert instrument.maximum_notes == index + 1
        assert instrument.voice_number == 200 + index
        assert instrument.receive_channel == 16
        assert instrument.low_note == index
        assert instrument.high_note == 127
        assert instrument.detune == 7 + index
        assert instrument.note_shift == 24 + index
        assert instrument.volume == 99 - index
        assert instrument.output_assign == index % 4
        assert instrument.lfo_select == index % 4
        assert instrument.micro_tune_enable == index % 2
    assert performance.data[96] == 12
    assert performance.data[97] == 1
    assert performance.data[98] == 12
    assert performance.data[99] == 11
    assert performance.title == 'WT11 PMEM '
    assert packed.data == performance_memory()


def test_wt11_keeps_packed_dsp_enables_and_reserved_bits() -> None:
    packed = wt11.WT11PerformanceMemory2(data=performance_memory2())
    for index, enabled in enumerate(packed.dsp_enables):
        assert enabled == bool(index % 2)
    assert packed.settings.dsp_select == 10
    assert packed.settings.balance == 99
    assert packed.settings.time == 36
    assert packed.settings.lfo_control == 2
    assert packed.data == performance_memory2()


@pytest.mark.parametrize('kind', ['voice', 'performance', 'performance2'])
def test_wt11_reads_all_thirty_two_bank_records_at_their_original_offsets(
    kind: str,
) -> None:
    if kind == 'voice':
        data = b''.join(voice_memory()[:-1] + bytes([i]) for i in range(32))
        raw = message(bytes([4, 32, 0]), data)
    elif kind == 'performance':
        data = b''.join(performance_memory()[:-1] + bytes([32 + i]) for i in range(32))
        raw = message(bytes([0x7E, 19, 10]), b'LM  8976PM' + data)
    else:
        data = b''.join(performance_memory2()[:-1] + bytes([i]) for i in range(32))
        raw = message(bytes([0x7E, 6, 42]), b'LM  8073PM' + data)
    entries = wt11.parse_wt11(b'prefix' + raw)
    entry = entries[1]
    assert entry.offset == 6
    assert entry.diagnostic is None
    assert b''.join(x.data for x in entries) == b'prefix' + raw
    assert (
        entry.voice is None and entry.additional is None and entry.additional2 is None
    )
    assert entry.performance is None and entry.performance2 is None
    if kind == 'voice':
        assert entry.voice_bank is not None
        assert entry.voice_bank.data == data
        assert len(entry.voice_bank.voices) == 32
        assert b''.join(x.data for x in entry.voice_bank.voices) == data
        assert entry.performance_bank is None and entry.performance_bank2 is None
    elif kind == 'performance':
        assert entry.performance_bank is not None
        assert entry.performance_bank.data == data
        assert len(entry.performance_bank.performances) == 32
        assert b''.join(x.data for x in entry.performance_bank.performances) == data
        assert entry.voice_bank is None and entry.performance_bank2 is None
    else:
        assert entry.performance_bank2 is not None
        assert entry.performance_bank2.data == data
        assert len(entry.performance_bank2.performances) == 32
        assert b''.join(x.data for x in entry.performance_bank2.performances) == data
        assert entry.voice_bank is None and entry.performance_bank is None


@pytest.mark.parametrize('kind', ['voice', 'performance', 'performance2'])
@pytest.mark.parametrize(
    'fault', ['length', 'count', 'identifier', 'checksum', 'device', 'seven-bit']
)
def test_wt11_preserves_malformed_banks(kind: str, fault: str) -> None:
    if kind == 'voice':
        raw = bytearray(message(bytes([4, 32, 0]), voice_memory() * 32))
    elif kind == 'performance':
        raw = bytearray(
            message(bytes([0x7E, 19, 10]), b'LM  8976PM' + performance_memory() * 32)
        )
    else:
        raw = bytearray(
            message(bytes([0x7E, 6, 42]), b'LM  8073PM' + performance_memory2() * 32)
        )
    if fault == 'length':
        del raw[20]
    elif fault == 'count':
        raw[5] ^= 1
    elif fault == 'identifier':
        raw[3 if kind == 'voice' else 15] ^= 1
    elif fault == 'checksum':
        raw[-2] ^= 1
    elif fault == 'device':
        raw[2] = 16
    else:
        raw[20] = 128
    entry = wt11.parse_wt11(bytes(raw))[0]
    assert entry.data == raw
    assert entry.diagnostic is not None
    assert entry.voice_bank is None
    assert entry.performance_bank is None
    assert entry.performance_bank2 is None


def test_wt11_retains_invalid_packed_parameters_without_coercing_them() -> None:
    data = bytearray(voice_memory())
    data[5] = 127
    data[86] = 101
    packed = wt11.WT11VoiceMemory(data=bytes(data))
    assert packed.voice.parameter_diagnostic is not None
    assert packed.data == data
    with pytest.raises(ValueError, match='packed aftertouch pitch bias'):
        _ = packed.additional2


@pytest.mark.parametrize(
    'identifier',
    [
        b'LM  8976AE',
        b'LM  8023AE',
        b'LM  8976PE',
        b'LM  8073PE',
        b'LM  8976PM',
        b'LM  8073PM',
    ],
)
def test_wt11_does_not_treat_voice_bank_payload_bytes_as_message_identifiers(
    identifier: bytes,
) -> None:
    data = identifier + bytes(4096 - len(identifier))
    entry = wt11.parse_wt11(message(bytes([4, 32, 0]), data))[0]
    assert entry.diagnostic is None
    assert entry.voice_bank is not None
    assert entry.voice_bank.data == data
    assert entry.voice is None
    assert entry.additional is None and entry.additional2 is None
    assert entry.performance is None and entry.performance2 is None
    assert entry.performance_bank is None and entry.performance_bank2 is None


@pytest.mark.parametrize(
    'model,size',
    [
        (wt11.WT11VoiceMemory, 128),
        (wt11.WT11PerformanceMemory, 76),
        (wt11.WT11PerformanceMemory2, 25),
        (wt11.WT11VoiceBank, 4096),
        (wt11.WT11PerformanceBank, 2432),
        (wt11.WT11PerformanceBank2, 800),
    ],
)
def test_wt11_rejects_invalid_packed_record_and_bank_shapes(
    model: type[Model], size: int
) -> None:
    for data in (bytes(size - 1), bytes(size + 1), bytes([128]) + bytes(size - 1)):
        with pytest.raises(ValidationError):
            model(data=data)
