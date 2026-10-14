import pytest
from pydantic import ValidationError

from ufor.arpeggiator import PitchScale, ScaleMapping


def test_scale_defaults_and_custom_intervals() -> None:
    scale = PitchScale(root=2, intervals=[0, 3, 7])
    assert scale.mapping == ScaleMapping.nearest
    assert scale.degrees == 0
    assert PitchScale.model_validate_json(scale.model_dump_json()) == scale


@pytest.mark.parametrize(
    'fields',
    [
        {'root': -1},
        {'root': 12},
        {'root': True},
        {'intervals': []},
        {'intervals': [1, 3]},
        {'intervals': [0, 0]},
        {'intervals': [0, 7, 3]},
        {'intervals': [0, 12]},
        {'intervals': [0, 2.5]},
        {'degrees': True},
        {'degrees': 2**63},
        {'mapping': 'preserve'},
    ],
)
def test_invalid_scale_definitions_are_rejected(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PitchScale.model_validate({'root': 0, 'intervals': [0, 2, 4], **fields})
