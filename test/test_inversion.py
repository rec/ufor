import pytest
from pydantic import ValidationError

from ufor.arpeggiator import Arpeggiator


@pytest.mark.parametrize('count', [True, 1.5, 2**63, -(2**63) - 1])
def test_inversion_requires_a_signed_integer(count: object) -> None:
    with pytest.raises(ValidationError):
        Arpeggiator.model_validate(
            {'rhythm': {'kind': 'grid', 'step': '1 beat'}, 'inversion': count}
        )


@pytest.mark.parametrize('kind', ['history', 'phrase'])
def test_inversion_rejects_banks_without_a_current_chord(kind: str) -> None:
    with pytest.raises(ValidationError):
        Arpeggiator.model_validate(
            {
                'bank': {'kind': kind},
                'rhythm': {'kind': 'grid', 'step': '1 beat'},
                'inversion': 1,
            }
        )
