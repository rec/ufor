from pathlib import Path

import pytest

from ufor import audio_effects


@pytest.mark.parametrize('rate,frames', [(44100, 221), (48000, 240), (96000, 480)])
def test_limiter_latency_rounds_up_lookahead_at_the_render_rate(
    rate: int, frames: int
) -> None:
    graph = audio_effects.EffectGraph.model_validate_json(
        (Path(__file__).parents[1] / 'conformance/limiter.json').read_text()
    )
    assert graph.latencies(rate) == {'limit': frames}
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )


@pytest.mark.parametrize(
    'parameter,value',
    [('ceiling_db', 1), ('release_seconds', -1), ('lookahead_seconds', 0.01)],
)
def test_limiter_rejects_invalid_or_fixed_control_targets(
    parameter: str, value: float
) -> None:
    with pytest.raises(ValueError):
        audio_effects.validate_parameter(
            audio_effects.Limiter(name='limit'), parameter, value
        )


def test_limiter_uses_explicit_units_and_requires_positive_lookahead() -> None:
    limiter = audio_effects.Limiter.model_validate(
        {
            'name': 'limit',
            'lookahead_seconds': '5 ms',
            'release_seconds': '50 ms',
            'ceiling_db': '-1 dB',
        }
    )
    assert (limiter.lookahead_seconds, limiter.release_seconds, limiter.ceiling_db) == (
        0.005,
        0.05,
        -1,
    )
    action = audio_effects.ParameterAction.model_validate(
        {
            'tick': 0,
            'ordinal': 0,
            'processor': 'limit',
            'parameter': 'ceiling_db',
            'value': '-3 dB',
        }
    )
    assert action.value == -3
    with pytest.raises(ValueError):
        audio_effects.Limiter(name='limit', lookahead_seconds=0)
