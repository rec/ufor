import pytest
from pydantic import ValidationError

from ufor.arpeggiator import SelectionOffset


@pytest.mark.parametrize('boundary', ['wrap', 'rest'])
def test_offset_keeps_signed_ranks_and_boundary(boundary: str) -> None:
    offset = SelectionOffset.model_validate({'ranks': -1, 'boundary': boundary})
    assert offset.ranks == -1
    assert SelectionOffset.model_validate_json(offset.model_dump_json()) == offset


@pytest.mark.parametrize('value', [True, 0.5, '1', 2**63, -(2**63) - 1])
def test_offset_rejects_noninteger_or_unrepresentable_ranks(value: object) -> None:
    with pytest.raises(ValidationError):
        SelectionOffset.model_validate({'ranks': value})
