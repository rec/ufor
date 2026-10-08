from fractions import Fraction

import pytest
from pydantic import ValidationError

from ufor.arpeggiator_ports import ArpeggiatorControl, ArpeggiatorPortBatch


@pytest.mark.parametrize(
    'port,value',
    [
        ('gate', '3/2'),
        ('density', '2/3'),
        ('transposition', '-12'),
        ('selection_offset', '-1'),
    ],
)
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
        ('transposition', '1/2'),
        ('transposition', str(2**63)),
        ('selection_offset', '1/2'),
        ('selection_offset', str(2**63)),
        ('breath', '-1/100'),
        ('pressure', '101/100'),
        ('bend', '-101/100'),
        ('bend', '101/100'),
    ],
)
def test_invalid_port_controls_are_rejected(port: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ArpeggiatorControl.model_validate({'port': port, 'value': value})


def test_port_batch_round_trip_preserves_event_order_and_overflow() -> None:
    batch = ArpeggiatorPortBatch.model_validate(
        {
            'events': [
                {'at': '1/4', 'port': 'capture_ready', 'index': 1, 'revision': 2},
                {'at': '1/4', 'port': 'cycle', 'index': 1, 'revision': 2},
                {'at': '1/4', 'port': 'step', 'index': 1, 'revision': 2},
                {'at': '1/4', 'port': 'hit', 'index': 1, 'revision': 2},
            ],
            'exhausted': True,
            'notes': [
                {
                    'at': '1/4',
                    'port': 'note_start',
                    'occurrence': 0,
                    'source': 'input:0',
                    'key': 60,
                    'velocity': 100,
                },
                {
                    'at': '1/2',
                    'port': 'note_end',
                    'occurrence': 0,
                    'source': 'input:0',
                    'key': 60,
                    'velocity': 20,
                },
            ],
        }
    )
    assert ArpeggiatorPortBatch.model_validate_json(batch.model_dump_json()) == batch
