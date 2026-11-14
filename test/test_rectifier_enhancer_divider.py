import pytest

from ufor import audio_effects


def test_enhancer_aligns_explicit_dry_and_high_band_branches() -> None:
    graph = audio_effects.enhancer_graph(
        'exciter',
        audio_effects.AttachmentScope.master,
        audio_effects.GraphInput(
            name='main', channels=['left', 'right'], source=audio_effects.MainStream()
        ),
        997,
    )
    assert graph.latencies()['exciter-mix'] == 48
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    mix = graph.processors[-1]
    assert isinstance(mix, audio_effects.Mixer)
    assert mix.inputs[0].gain_db == 0
    assert 10 ** (mix.inputs[1].gain_db / 20) == pytest.approx(0.25)


@pytest.mark.parametrize('curve', ['half_wave', 'full_wave'])
def test_rectifiers_keep_the_waveshaper_control_contract(curve: str) -> None:
    processor = audio_effects.Waveshaper.model_validate(
        {'name': 'rectify', 'curve': curve}
    )
    audio_effects.validate_parameter(processor, 'bias', -0.25)
    with pytest.raises(ValueError):
        audio_effects.validate_parameter(processor, 'curve', 0)


@pytest.mark.parametrize(
    'parameter,value',
    [
        ('threshold', 0),
        ('threshold', -1),
        ('attack_seconds', -1),
        ('release_seconds', -1),
    ],
)
def test_divider_rejects_invalid_detector_controls(
    parameter: str, value: float
) -> None:
    with pytest.raises(ValueError):
        audio_effects.validate_parameter(
            audio_effects.OctaveDivider(name='octave'), parameter, value
        )


def test_divider_roundtrips_units_and_rejects_invalid_state_floor() -> None:
    definition = audio_effects.OctaveDivider.model_validate(
        {'name': 'octave', 'attack_seconds': '1 ms', 'release_seconds': '50 ms'}
    )
    assert (definition.attack_seconds, definition.release_seconds) == (0.001, 0.05)
    assert (
        audio_effects.OctaveDivider.model_validate_json(definition.model_dump_json())
        == definition
    )
    with pytest.raises(ValueError, match='state_floor'):
        audio_effects.OctaveDivider(name='octave', state_floor=1)
