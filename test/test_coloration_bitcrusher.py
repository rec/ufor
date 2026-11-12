from pathlib import Path
from typing import Literal

import pytest

from ufor import audio_effects


@pytest.mark.parametrize(
    'profile,cutoff,bias', [('tape', 8000, 0), ('tube', 12000, 0.25)]
)
def test_coloration_composes_declared_profiles_with_fixed_latency(
    profile: Literal['tape', 'tube'], cutoff: float, bias: float
) -> None:
    graph = audio_effects.coloration_graph(
        'color',
        audio_effects.AttachmentScope.master,
        audio_effects.GraphInput(
            name='main', channels=['left', 'right'], source=audio_effects.MainStream()
        ),
        profile,
        997,
    )
    assert graph.latencies() == {'color-dc': 0, 'color-drive': 48, 'color-tone': 48}
    drive = graph.processors[1]
    assert isinstance(drive, audio_effects.Waveshaper)
    assert (drive.drive, drive.bias, drive.output_gain_db) == (2, bias, 0)
    tone = graph.processors[2]
    assert isinstance(tone, audio_effects.Filter)
    assert tone.filters[0].cutoff_hz == cutoff
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )


@pytest.mark.parametrize(
    'parameter,value',
    [
        ('bits', 0),
        ('bits', 25),
        ('bits', 2.5),
        ('hold_frames', 0),
        ('hold_frames', 65537),
        ('hold_frames', 1.5),
    ],
)
def test_bitcrusher_rejects_out_of_profile_integer_controls(
    parameter: str, value: float
) -> None:
    with pytest.raises(ValueError):
        audio_effects.validate_parameter(
            audio_effects.Bitcrusher(name='crush'), parameter, value
        )


def test_bitcrusher_keeps_integer_capture_requests_distinct_from_mix_ramps() -> None:
    graph = audio_effects.EffectGraph.model_validate_json(
        (Path(__file__).parents[1] / 'conformance/bitcrusher.json').read_text()
    )
    assert graph.latencies() == {'crush': 0}
    for parameter, value in [('bits', 1), ('bits', 24), ('hold_frames', 65536)]:
        audio_effects.validate_action(
            graph,
            audio_effects.ParameterAction(
                tick=0, ordinal=0, processor='crush', parameter=parameter, value=value
            ),
        )
        with pytest.raises(ValueError, match='ramps'):
            audio_effects.validate_action(
                graph,
                audio_effects.ParameterAction(
                    tick=0,
                    ordinal=0,
                    processor='crush',
                    parameter=parameter,
                    value=value,
                    duration_frames=1,
                ),
            )
    audio_effects.validate_action(
        graph,
        audio_effects.ParameterAction(
            tick=0,
            ordinal=0,
            processor='crush',
            parameter='mix',
            value=0.5,
            duration_frames=64,
        ),
    )
