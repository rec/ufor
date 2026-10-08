from math import nextafter

import pytest
from pydantic import ValidationError

from ufor.motion import Patch, Quantize, quantize_value, transform_value


@pytest.mark.parametrize(
    'value,expected',
    [(-1.25, -1), (-0.75, -0.5), (-0.25, 0), (0.25, 0.5), (0.75, 1), (1.25, 1.5)],
)
def test_quantize_half_steps_choose_the_higher_value(
    value: float, expected: float
) -> None:
    body = Quantize(input='signal', step=0.5)
    assert quantize_value(body, value) == expected
    assert transform_value(body, {'signal': value}) == expected
    assert quantize_value(body, nextafter(value, float('-inf'))) == expected - 0.5
    assert quantize_value(body, nextafter(value, float('inf'))) == expected


def test_quantize_origin_and_range_do_not_clip() -> None:
    body = Patch.model_validate(
        {
            'motions': {
                'wave': {'kind': 'cycle', 'rate': '1'},
                'steps': {
                    'kind': 'quantize',
                    'input': 'wave',
                    'step': 0.75,
                    'origin': 0.125,
                },
            },
            'outputs': {'value': 'steps'},
        }
    )
    assert body.signal_ranges['steps'] == (-0.625, 0.875)
    assert body.signal_order == ['wave', 'steps']
    assert Patch.model_validate_json(body.model_dump_json()) == body
    node = Quantize(input='wave', step=0.75, origin=0.125)
    assert quantize_value(node, 1.3) == 1.625
    raw = body.model_dump()
    raw['motions']['steps']['input'] = 'steps'
    with pytest.raises(ValidationError, match='cycle'):
        Patch.model_validate(raw)
    raw['motions']['steps']['input'] = 'missing'
    with pytest.raises(ValidationError, match='unknown child'):
        Patch.model_validate(raw)


@pytest.mark.parametrize(
    'step,origin', [(0, 0), (-1, 0), (float('inf'), 0), (1, float('nan'))]
)
def test_quantize_rejects_invalid_grids(step: float, origin: float) -> None:
    with pytest.raises(ValidationError):
        Quantize(input='signal', step=step, origin=origin)
