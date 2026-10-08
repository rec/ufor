import pytest
from pydantic import ValidationError

from ufor.arpeggiator import Transposition


@pytest.mark.parametrize('boundary', ['drop', 'fold', 'error'])
def test_transposition_keeps_exact_signed_semitones(boundary: str) -> None:
    value = Transposition.model_validate({'semitones': -12, 'boundary': boundary})
    assert value.semitones == -12
    assert Transposition.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize('value', [True, 0.5, '12', 2**63, -(2**63) - 1])
def test_transposition_rejects_noninteger_or_unrepresentable_offsets(
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        Transposition.model_validate({'semitones': value})
