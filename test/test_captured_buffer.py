import json
from pathlib import Path
from typing import Literal

import pytest
from pydantic import TypeAdapter, ValidationError

from ufor import audio_effects


def test_captured_modes_and_actions_roundtrip_and_preserve_layout() -> None:
    recipe = json.loads(
        (Path(__file__).parents[1] / 'conformance/captured-buffer.json').read_text()
    )
    processors = TypeAdapter(list[audio_effects.Processor]).validate_python(
        recipe['processors']
    )
    actions = TypeAdapter(list[audio_effects.EffectAction]).validate_python(
        recipe['actions']
    )
    graph = audio_effects.EffectGraph(
        scope=audio_effects.AttachmentScope.master,
        inputs=[
            audio_effects.GraphInput(
                name='main',
                channels=['left', 'right'],
                source=audio_effects.MainStream(),
            )
        ],
        processors=processors,
        connections=[
            audio_effects.Connection(
                processor=p.name,
                port='input',
                source=audio_effects.InputSource(input='main')
                if i == 0
                else audio_effects.ProcessorSource(processor=processors[i - 1].name),
            )
            for i, p in enumerate(processors)
        ],
        output=audio_effects.ProcessorSource(processor='stutter'),
        maximum_block_frames=1024,
    )
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    assert graph.output_channels() == ['left', 'right']
    assert graph.latencies(48000) == {'reverse': 0, 'scrub': 0, 'stutter': 0}
    for action in actions:
        audio_effects.validate_action(graph, action)
    assert audio_effects.ActionBatch(actions=[actions[1]]).lifecycle
    assert not audio_effects.ActionBatch(actions=[actions[0]]).lifecycle


@pytest.mark.parametrize('mode', ['reverse', 'stutter'])
def test_position_is_only_a_scrub_control(mode: Literal['reverse', 'stutter']) -> None:
    with pytest.raises(ValidationError, match='scrub'):
        audio_effects.CapturedBuffer(name='buffer', mode=mode, position=0.5)
    with pytest.raises(ValueError, match='scrub'):
        audio_effects.validate_parameter(
            audio_effects.CapturedBuffer(name='buffer', mode=mode), 'position', 0.5
        )


@pytest.mark.parametrize('seconds', [0, -0.1, 2.001, float('nan')])
def test_capture_window_requires_a_positive_duration_at_most_two_seconds(
    seconds: float,
) -> None:
    with pytest.raises(ValidationError):
        audio_effects.CapturedBuffer(
            name='buffer', mode='reverse', window_seconds=seconds
        )


@pytest.mark.parametrize('capacity', [0, -1, True, 1.5])
def test_capture_command_capacity_requires_a_positive_integer(capacity: object) -> None:
    with pytest.raises(ValidationError):
        audio_effects.CapturedBuffer.model_validate(
            {'name': 'buffer', 'mode': 'stutter', 'maximum_pending_actions': capacity}
        )
