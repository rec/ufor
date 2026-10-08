from fractions import Fraction

import pytest
from pydantic import ValidationError

from ufor.arpeggiator_ports import ArpeggiatorControl, ArpeggiatorPortBatch


@pytest.mark.parametrize('port,value', [('gate', '3/2'), ('density', '2/3')])
def test_port_controls_keep_exact_rationals(port: str, value: str) -> None:
    control = ArpeggiatorControl.model_validate({'port': port, 'value': value})
    assert control.value == Fraction(value)
    assert ArpeggiatorControl.model_validate_json(control.model_dump_json()) == control


@pytest.mark.parametrize(
    'port,value',
    [
        ('gate', '-1'),
        ('density', '-1'),
        ('density', '2'),
        ('other', '1'),
        ('gate', 0.5),
    ],
)
def test_invalid_port_controls_are_rejected(port: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ArpeggiatorControl.model_validate({'port': port, 'value': value})


def test_port_batch_round_trip_preserves_event_order_and_overflow() -> None:
    batch = ArpeggiatorPortBatch.model_validate(
        {
            'events': [
                {'at': '1/4', 'port': 'step', 'index': 1, 'revision': 2},
                {'at': '1/4', 'port': 'hit', 'index': 1, 'revision': 2},
            ],
            'exhausted': True,
        }
    )
    assert ArpeggiatorPortBatch.model_validate_json(batch.model_dump_json()) == batch
