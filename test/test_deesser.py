from pathlib import Path

from ufor import audio_effects


def test_deesser_composes_the_declared_detector_and_unfiltered_signal_path() -> None:
    expected = audio_effects.EffectGraph.model_validate_json(
        (Path(__file__).parents[1] / 'conformance/de-esser.json').read_text()
    )
    graph = audio_effects.deesser_graph('ess', expected.scope, expected.inputs[0], 997)
    assert graph == expected
    assert graph.latencies(48000)['ess-compressor'] == 0
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    for processor, parameter, value in [
        ('ess-detector', 'band-cutoff_hz', 7500),
        ('ess-detector', 'band-q', 2),
        ('ess-compressor', 'threshold_db', -30),
        ('ess-compressor', 'mix', 0.5),
    ]:
        audio_effects.validate_action(
            graph,
            audio_effects.ParameterAction(
                tick=0, ordinal=0, processor=processor, parameter=parameter, value=value
            ),
        )


def test_deesser_preserves_attachment_owner_and_named_layout() -> None:
    graph = audio_effects.deesser_graph(
        'ess',
        audio_effects.AttachmentScope.instrument,
        audio_effects.GraphInput(
            name='voice', channels=['mono'], source=audio_effects.MainStream()
        ),
        256,
        owner='vocal',
    )
    assert graph.owner == 'vocal'
    assert graph.inputs[0].channels == ['mono']
