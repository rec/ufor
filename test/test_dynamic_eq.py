from pathlib import Path

import pytest

from ufor import audio_effects
from ufor.modulation import Target, Unit


def test_dynamic_eq_roundtrips_units_and_tuning_actions() -> None:
    path = Path(__file__).parents[1] / 'conformance/dynamic-eq.json'
    graph = audio_effects.EffectGraph.model_validate_json(path.read_text())
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    assert graph.latencies(48000) == {'bell': 0}
    assert graph.parameter_definition(Target(name='bell', parameter='center_hz')) == (
        Unit.hz,
        1000,
    )
    action = audio_effects.ParameterAction(
        tick=17,
        ordinal=0,
        processor='bell',
        parameter='maximum_cut_db',
        value='6 dB',
        duration_frames=64,
    )
    audio_effects.validate_action(graph, action)
    assert action.value == 6
    audio_effects.validate_action(
        graph,
        audio_effects.BypassAction(tick=19, ordinal=0, processor='bell', bypassed=True),
    )
    audio_effects.validate_parameter(graph.processors[0], 'center_hz', 2000)
    audio_effects.validate_parameter(graph.processors[0], 'q', 2)


@pytest.mark.parametrize(
    'parameter,value',
    [
        ('center_hz', 0),
        ('q', 0),
        ('ratio', 0.5),
        ('maximum_cut_db', -1),
        ('attack_seconds', -1),
        ('release_seconds', -1),
        ('knee_db', -1),
        ('threshold_db', float('inf')),
        ('mix', 2),
        ('makeup_db', 1),
    ],
)
def test_dynamic_eq_rejects_invalid_or_unsupported_controls(
    parameter: str, value: float
) -> None:
    with pytest.raises(ValueError):
        audio_effects.validate_parameter(
            audio_effects.DynamicEQ(name='bell'), parameter, value
        )


def test_dynamic_eq_defaults_are_neutral_and_tail_floor_is_bounded() -> None:
    assert audio_effects.DynamicEQ(name='bell').ratio == 1
    with pytest.raises(ValueError, match='state_floor'):
        audio_effects.DynamicEQ(name='bell', state_floor=1, tail_threshold=1)
