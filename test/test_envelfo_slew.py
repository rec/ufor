import pytest
from pydantic import ValidationError

from ufor.envelfo import EnvelfoUse, Patch, Slew


def test_slew_range_includes_initial_value_and_validates_dependencies() -> None:
    body = Patch.model_validate(
        {
            'envelfos': {
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
        EnvelfoUse(body=body, scope='part')
    raw = body.model_dump()
    raw['envelfos']['smooth']['input'] = 'smooth'
    with pytest.raises(ValidationError, match='cycle'):
        Patch.model_validate(raw)


@pytest.mark.parametrize('rise,fall', [(-1, 1), (1, -1), (float('inf'), 1)])
def test_slew_rejects_invalid_rates(rise: float, fall: float) -> None:
    with pytest.raises(ValidationError):
        Slew(input='signal', rise=rise, fall=fall)
