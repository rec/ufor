from pathlib import Path

import pytest

from ufor import audio_effects


def test_transient_shaper_roundtrips_units_without_latency() -> None:
    graph = audio_effects.EffectGraph.model_validate_json(
        (Path(__file__).parents[1] / 'conformance/transient-shaper.json').read_text()
    )
    assert graph.latencies(48000) == {'shape': 0}
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    shape = graph.processors[0]
    assert isinstance(shape, audio_effects.TransientShaper)
    assert (shape.attack_gain_db, shape.sustain_gain_db) == (6, -3)
    action = audio_effects.ParameterAction.model_validate(
        {
            'tick': 0,
            'ordinal': 0,
            'processor': 'shape',
            'parameter': 'attack_gain_db',
            'value': '-12 dB',
            'duration_frames': 64,
        }
    )
    audio_effects.validate_action(graph, action)
    assert action.value == -12


@pytest.mark.parametrize('parameter', ['attack_gain_db', 'sustain_gain_db'])
@pytest.mark.parametrize('value', [-24, 0, 24])
def test_transient_shaper_accepts_bounded_gain_controls(
    parameter: str, value: float
) -> None:
    audio_effects.validate_parameter(
        audio_effects.TransientShaper(name='shape'), parameter, value
    )


@pytest.mark.parametrize(
    'parameter,value',
    [
        ('attack_gain_db', -24.1),
        ('sustain_gain_db', 24.1),
        ('fast_attack_seconds', 0.1),
    ],
)
def test_transient_shaper_rejects_out_of_profile_controls(
    parameter: str, value: float
) -> None:
    with pytest.raises(ValueError):
        audio_effects.validate_parameter(
            audio_effects.TransientShaper(name='shape'), parameter, value
        )
