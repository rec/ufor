from pathlib import Path

import pytest

from ufor import audio_effects


def test_multiband_roundtrips_units_and_band_actions() -> None:
    graph = audio_effects.EffectGraph.model_validate_json(
        (
            Path(__file__).parents[1] / 'conformance/multiband-compressor.json'
        ).read_text()
    )
    assert graph.latencies(48000) == {'bands': 0}
    assert graph.output_channels() == ['left', 'right']
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    action = audio_effects.ParameterAction(
        tick=0,
        ordinal=0,
        processor='bands',
        parameter='high-attack_seconds',
        value='2 ms',
        duration_frames=64,
    )
    audio_effects.validate_action(graph, action)
    assert action.value == 0.002
    with pytest.raises(ValueError, match='always wet'):
        audio_effects.validate_action(
            graph,
            audio_effects.BypassAction(
                tick=0, ordinal=0, processor='bands', bypassed=True
            ),
        )


@pytest.mark.parametrize(
    'parameter,value',
    [
        ('low-ratio', 0.5),
        ('mid-knee_db', -1),
        ('high-release_seconds', -1),
        ('low-makeup_db', float('inf')),
        ('lower_crossover_hz', 300),
        ('mix', 0.5),
        ('bass-ratio', 2),
    ],
)
def test_multiband_rejects_invalid_or_fixed_controls(
    parameter: str, value: float
) -> None:
    with pytest.raises(ValueError):
        audio_effects.validate_parameter(
            audio_effects.MultibandCompressor(name='bands'), parameter, value
        )


def test_multiband_requires_ordered_crossovers_and_tail_floor() -> None:
    with pytest.raises(ValueError, match='strictly increase'):
        audio_effects.MultibandCompressor(
            name='bands', lower_crossover_hz=4000, upper_crossover_hz=200
        )
    with pytest.raises(ValueError, match='state_floor'):
        audio_effects.MultibandCompressor(name='bands', state_floor=1, tail_threshold=1)
