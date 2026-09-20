import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor import audio_effects

DATA = json.loads((Path(__file__).parents[1] / 'conformance/effects.json').read_text())


def test_effect_graph_conformance() -> None:
    graph = audio_effects.EffectGraph.model_validate(DATA['graph'])

    assert graph.order() == DATA['order']
    assert graph.output_channels() == DATA['output_channels']
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )


def test_effect_action_batch_conformance() -> None:
    graph = audio_effects.EffectGraph.model_validate(DATA['graph'])
    batch = audio_effects.ActionBatch.model_validate(DATA['batch'])

    audio_effects.validate_batch(graph, batch)
    assert not batch.lifecycle
    assert (
        audio_effects.ActionBatch.model_validate_json(batch.model_dump_json()) == batch
    )


def test_graph_rejects_cycle() -> None:
    value = DATA['graph'] | {
        'connections': [
            {
                'processor': 'trim',
                'port': 'input',
                'source': {'kind': 'processor', 'processor': 'ring'},
            },
            *DATA['graph']['connections'][1:],
        ]
    }

    with pytest.raises(ValidationError, match='cycle'):
        audio_effects.EffectGraph.model_validate(value)


def test_graph_rejects_missing_port() -> None:
    value = DATA['graph'] | {'connections': DATA['graph']['connections'][:-1]}

    with pytest.raises(ValidationError, match='unconnected ports'):
        audio_effects.EffectGraph.model_validate(value)


def test_graph_rejects_mismatched_multiply_channels() -> None:
    value = json.loads(json.dumps(DATA['graph']))
    value['inputs'][1]['channels'] = ['mono']

    with pytest.raises(ValidationError, match='matching channel layouts'):
        audio_effects.EffectGraph.model_validate(value)


@pytest.mark.parametrize('case', DATA['grain_windows'])
def test_grain_window_conformance(case: dict[str, object]) -> None:
    assert audio_effects.grain_window(case['index'], case['frames']) == pytest.approx(
        case['value'], abs=1e-15
    )


def test_grain_scheduler_conformance() -> None:
    case = DATA['grain_scheduler']
    phase = 0.0
    launches: list[bool] = []
    for _ in case['launches']:
        launch, phase = audio_effects.grain_launches(
            phase, case['density_hz'], case['sample_rate']
        )
        launches.append(launch)

    assert launches == case['launches']
    assert phase == 0


@pytest.mark.parametrize('case', DATA['grain_jitter'])
def test_grain_jitter_conformance(case: dict[str, object]) -> None:
    assert audio_effects.grain_jitter(case['counter']) == case['value']


def test_parameter_validation() -> None:
    graph = audio_effects.EffectGraph.model_validate(DATA['graph'])
    invalid = audio_effects.ParameterAction(
        tick=0,
        ordinal=0,
        processor='ring',
        parameter='gain_db',
        value=1.0,
    )

    with pytest.raises(ValueError, match='unsupported parameter'):
        audio_effects.validate_action(graph, invalid)


def test_granulator_requires_its_read_history() -> None:
    with pytest.raises(ValidationError, match='history is too short'):
        audio_effects.Granulator(
            name='cloud',
            duration_seconds=0.1,
            density_hz=20.0,
            lookback_seconds=0.2,
            playback_ratio=2.0,
            position_jitter_seconds=0.05,
            history_seconds=0.44,
            maximum_grains=8,
        )
