import pytest
from pydantic import ValidationError

from ufor.motion import Latch, MotionUse, Patch, latch_value


def test_latch_captures_on_activation_and_holds_until_cleared() -> None:
    assert latch_value(-0.25, None) == -0.25
    assert latch_value(0.75, -0.25) == -0.25
    assert latch_value(0.75, None) == 0.75
    assert latch_value(-0.5, 0.75) == 0.75


def test_latch_graph_validates_capture_commands_ranges_and_scope() -> None:
    body = Patch.model_validate(
        {
            'motions': {
                'wave': {
                    'kind': 'cycle',
                    'rate': '2',
                    'markers': [{'name': 'tick', 'position': '1/4'}],
                },
                'held': {'kind': 'latch', 'input': 'wave'},
            },
            'outputs': {'value': 'held'},
            'events': [
                {
                    'source': 'wave.tick',
                    'target': 'held',
                    'action': 'capture',
                    'delay': '1/8',
                }
            ],
        }
    )
    assert isinstance(body.motions['held'], Latch)
    assert body.signal_ranges['held'] == (-1, 1)
    assert body.signal_order == ['wave', 'held']
    assert Patch.model_validate_json(body.model_dump_json()) == body
    with pytest.raises(ValidationError, match='latch requires voice scope'):
        MotionUse(body=body, scope='instrument')
    raw = body.model_dump()
    raw['events'][0]['target'] = 'wave'
    with pytest.raises(ValidationError, match='capture target must be a Latch'):
        Patch.model_validate(raw)
    raw['events'][0]['target'] = 'held'
    raw['events'][0]['action'] = 'sample'
    with pytest.raises(ValidationError, match='sample target'):
        Patch.model_validate(raw)
    raw['events'] = []
    raw['motions']['held']['input'] = 'held'
    with pytest.raises(ValidationError, match='cycle'):
        Patch.model_validate(raw)
