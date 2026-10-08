from fractions import Fraction

import pytest
from pydantic import ValidationError

from ufor.motion import MotionUse, Patch, Slew, slew_value


def test_slew_limits_each_direction_and_does_not_overshoot() -> None:
    body = Slew(input='pressure', rise=2, fall=1)
    assert slew_value(body, 0.5, None, Fraction(1, 10)) == 0.5
    assert slew_value(body, 1, 0.5, Fraction(1, 10)) == 0.7
    assert slew_value(body, 0, 0.5, Fraction(1, 10)) == 0.4
    assert slew_value(body, 0.6, 0.5, Fraction(1, 10)) == 0.6
    assert slew_value(body, 0.5, 0.6, Fraction(1)) == 0.5
    assert slew_value(body, 1, 0.5, Fraction(0)) == 0.5
    wide = Slew(input='signal', rise=1e308, fall=1e308)
    assert slew_value(wide, 1e308, -1e308, Fraction(2)) == 1e308
    assert slew_value(wide, -1e308, 1e308, Fraction(2)) == -1e308


def test_slew_explicit_initial_and_zero_rates_hold_direction() -> None:
    body = Slew(input='pressure', rise=0, fall=1, initial=2)
    assert slew_value(body, 0, None, Fraction(1)) == 2
    assert slew_value(body, 0, 2, Fraction(1, 2)) == 1.5
    assert slew_value(body, 3, 2, Fraction(1)) == 2
    assert slew_value(Slew(input='signal', rise=1, fall=0), 0, 1, Fraction(1)) == 1


def test_slew_range_includes_initial_value_and_validates_dependencies() -> None:
    body = Patch.model_validate(
        {
            'motions': {
                'clock': {'kind': 'cycle', 'rate': '1'},
                'smooth': {
                    'kind': 'slew',
                    'input': 'clock',
                    'rise': 2,
                    'fall': 1,
                    'initial': 3,
                },
            },
            'outputs': {'value': 'smooth'},
        }
    )
    assert body.signal_ranges['smooth'] == (-1, 3)
    assert body.signal_order.index('clock') < body.signal_order.index('smooth')
    assert Patch.model_validate_json(body.model_dump_json()) == body
    with pytest.raises(ValidationError, match='slew requires voice scope'):
        MotionUse(body=body, scope='part')
    raw = body.model_dump()
    raw['motions']['smooth']['input'] = 'smooth'
    with pytest.raises(ValidationError, match='cycle'):
        Patch.model_validate(raw)


@pytest.mark.parametrize('rise,fall', [(-1, 1), (1, -1), (float('inf'), 1)])
def test_slew_rejects_invalid_rates(rise: float, fall: float) -> None:
    with pytest.raises(ValidationError):
        Slew(input='signal', rise=rise, fall=fall)
