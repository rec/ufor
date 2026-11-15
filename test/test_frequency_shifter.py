from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from ufor import audio_effects, modulation


def test_frequency_shifter_contract_roundtrips_and_declares_fixed_latency() -> None:
    definition = TypeAdapter(audio_effects.Processor).validate_json(
        (Path(__file__).parents[1] / 'conformance/frequency-shifter.json').read_text()
    )
    assert isinstance(definition, audio_effects.FrequencyShifter)
    assert definition.shift_hz == -250
    assert audio_effects.processor_latency(definition, 48000) == 512
    assert audio_effects.processor_latency(definition, 96000) == 512
    assert (
        TypeAdapter(audio_effects.Processor).validate_json(definition.model_dump_json())
        == definition
    )
    action = audio_effects.ParameterAction(
        tick=0, ordinal=0, processor='shift', parameter='shift_hz', value='-2 kHz'
    )
    audio_effects.validate_parameter(definition, action.parameter, action.value)
    assert action.value == -2000


@pytest.mark.parametrize('value', [-2000.1, 2000.1, float('nan'), float('inf')])
def test_frequency_shifter_rejects_out_of_range_shift(value: float) -> None:
    with pytest.raises(ValidationError):
        audio_effects.FrequencyShifter(name='shift', shift_hz=value)
    with pytest.raises(ValueError):
        audio_effects.validate_parameter(
            audio_effects.FrequencyShifter(name='shift'), 'shift_hz', value
        )


def test_frequency_shift_modulation_has_signed_hertz_domain() -> None:
    graph = audio_effects.EffectGraph(
        scope=audio_effects.AttachmentScope.master,
        inputs=[
            audio_effects.GraphInput(
                name='main',
                channels=['left', 'right'],
                source=audio_effects.MainStream(),
            )
        ],
        processors=[audio_effects.FrequencyShifter(name='shift')],
        connections=[
            audio_effects.Connection(
                processor='shift',
                port='input',
                source=audio_effects.InputSource(input='main'),
            )
        ],
        output=audio_effects.ProcessorSource(processor='shift'),
        maximum_block_frames=1024,
    )
    assert graph.parameter_definition(
        modulation.Target(name='shift', parameter='shift_hz')
    ) == (modulation.Unit.hz_offset, 0)
    assert graph.output_channels() == ['left', 'right']
    assert graph.latencies(48000) == {'shift': 512}
