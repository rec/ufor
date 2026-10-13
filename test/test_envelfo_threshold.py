import pytest
from pydantic import ValidationError

from ufor.envelfo import Patch, Threshold


def test_threshold_patch_exposes_gate_and_event_ports() -> None:
    body = Patch.model_validate(
        {
            'envelfos': {
                'clock': {'kind': 'lfo', 'rate': '1'},
                'edge': {
                    'kind': 'threshold',
                    'input': 'clock',
                    'lower': -0.2,
                    'upper': 0.2,
                },
                'random': {'kind': 'sample_hold'},
            },
            'outputs': {'value': 'edge'},
            'event_outputs': {'up': 'edge.rising'},
            'events': [
                {'source': 'edge.falling', 'target': 'random', 'action': 'sample'}
            ],
        }
    )
    assert body.signal_ranges['edge'] == (0, 1)
    assert body.signal_order.index('clock') < body.signal_order.index('edge')
    assert Patch.model_validate_json(body.model_dump_json()) == body
    with pytest.raises(ValidationError, match='requires voice scope'):
        type(body).model_validate(body.model_dump() | {'scope': 'instrument'})
    raw = body.model_dump()
    raw['events'][0]['source'] = 'edge.unknown'
    with pytest.raises(ValidationError, match='unknown'):
        Patch.model_validate(raw)


@pytest.mark.parametrize('lower,upper', [(1, 1), (2, 1)])
def test_threshold_rejects_empty_hysteresis(lower: float, upper: float) -> None:
    with pytest.raises(ValidationError, match='less than'):
        Threshold(input='signal', lower=lower, upper=upper)
