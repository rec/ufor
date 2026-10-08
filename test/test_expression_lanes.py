from fractions import Fraction

import pytest
from pydantic import ValidationError

from ufor.arpeggiator import Expression
from ufor.arpeggiator_ports import ArpeggiatorControl


def test_per_lane_sources_round_trip_without_changing_the_default_source() -> None:
    expression = Expression.model_validate(
        {'source': 'recorded', 'lanes': {'breath': 'motion', 'pressure': 'current'}}
    )
    assert expression.source == 'recorded'
    assert Expression.model_validate_json(expression.model_dump_json()) == expression


@pytest.mark.parametrize('lanes', [{'volume': 'motion'}, {'breath': 'combined'}])
def test_expression_rejects_undeclared_lanes_and_sources(lanes: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Expression.model_validate({'lanes': lanes})


@pytest.mark.parametrize(
    'port,value', [('breath', '1/2'), ('pressure', '0'), ('bend', '-1'), ('bend', '1')]
)
def test_expression_controls_retain_exact_normalized_samples(
    port: str, value: str
) -> None:
    control = ArpeggiatorControl.model_validate({'port': port, 'value': value})
    assert control.value == Fraction(value)
    assert ArpeggiatorControl.model_validate_json(control.model_dump_json()) == control
