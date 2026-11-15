from pathlib import Path

import pytest
from pydantic import TypeAdapter

from ufor import audio_effects, envelfo


def main_input() -> audio_effects.GraphInput:
    return audio_effects.GraphInput(
        name='main', channels=['left', 'right'], source=audio_effects.MainStream()
    )


@pytest.mark.parametrize('kind', ['tremolo', 'vibrato'])
def test_named_motion_profiles_roundtrip_shared_generator_and_layout(kind: str) -> None:
    recipe = TypeAdapter(dict[str, dict[str, float]]).validate_json(
        (Path(__file__).parents[1] / 'conformance/vibrato-tremolo.json').read_text()
    )[kind]
    if kind == 'tremolo':
        graph = audio_effects.tremolo_graph(
            'motion',
            audio_effects.AttachmentScope.master,
            main_input(),
            1024,
            rate_hz=recipe['rate_hz'],
            depth=recipe['depth'],
            phase=recipe['phase'],
        )
    else:
        graph = audio_effects.vibrato_graph(
            'motion',
            audio_effects.AttachmentScope.master,
            main_input(),
            1024,
            rate_hz=recipe['rate_hz'],
            depth_seconds=recipe['depth_seconds'],
            base_delay_seconds=recipe['base_delay_seconds'],
            maximum_delay_seconds=recipe['maximum_delay_seconds'],
            phase=recipe['phase'],
        )
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    assert graph.output_channels() == ['left', 'right']
    assert graph.latencies(48000)['motion'] == 0
    body = graph.envelfos['motion-motion']
    assert isinstance(body, envelfo.LFO) and body.rate == 5
    assert len(graph.modulation.routes) == 1
    if kind == 'tremolo':
        assert isinstance(graph.processors[-1], audio_effects.Crossfader)
        assert graph.parameter_definition(graph.modulation.routes[0].target)[1] == 0.75
    else:
        delay = graph.processors[0]
        assert isinstance(delay, audio_effects.ModulatedDelay)
        assert (delay.depth_seconds, delay.feedback, delay.mix) == (0, 0, 1)
        assert graph.modulation.parameters[0].minimum == pytest.approx(0.0045)


@pytest.mark.parametrize('depth', [-0.1, 1.1, float('nan')])
def test_tremolo_rejects_invalid_depth(depth: float) -> None:
    with pytest.raises(ValueError, match='depth'):
        audio_effects.tremolo_graph(
            'motion',
            audio_effects.AttachmentScope.master,
            main_input(),
            1024,
            depth=depth,
        )


@pytest.mark.parametrize('depth', [-1, 0.005, 0.006, float('nan')])
def test_vibrato_rejects_unbounded_or_nonpositive_delay_span(depth: float) -> None:
    with pytest.raises(ValueError, match='depth'):
        audio_effects.vibrato_graph(
            'motion',
            audio_effects.AttachmentScope.master,
            main_input(),
            1024,
            depth_seconds=depth,
        )


@pytest.mark.parametrize('kind', ['tremolo', 'vibrato'])
def test_motion_profiles_reject_invalid_clock(kind: str) -> None:
    helper = (
        audio_effects.tremolo_graph
        if kind == 'tremolo'
        else audio_effects.vibrato_graph
    )
    with pytest.raises(ValueError):
        helper(
            'motion',
            audio_effects.AttachmentScope.master,
            main_input(),
            1024,
            rate_hz=-1,
        )
    with pytest.raises(ValueError):
        helper(
            'motion', audio_effects.AttachmentScope.master, main_input(), 1024, phase=1
        )
