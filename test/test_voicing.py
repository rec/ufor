import pytest
from pydantic import ValidationError

from ufor.arpeggiator import Arpeggiator


def test_voicing_preserves_signed_offsets_and_defaults_to_disabled() -> None:
    rhythm = {'kind': 'grid', 'step': '1 beat'}
    assert Arpeggiator.model_validate({'rhythm': rhythm}).voicing is None
    arp = Arpeggiator.model_validate({'rhythm': rhythm, 'voicing': [0, -1, 2]})
    assert arp.voicing == [0, -1, 2]
    assert Arpeggiator.model_validate_json(arp.model_dump_json()) == arp


@pytest.mark.parametrize(
    'voicing', [[], [True], [1.5], [2**63], [-(2**63) - 1], 'open']
)
def test_voicing_requires_nonempty_signed_integer_offsets(voicing: object) -> None:
    with pytest.raises(ValidationError):
        Arpeggiator.model_validate(
            {'rhythm': {'kind': 'grid', 'step': '1 beat'}, 'voicing': voicing}
        )


@pytest.mark.parametrize('kind', ['history', 'phrase'])
def test_voicing_rejects_banks_without_chord_grouping(kind: str) -> None:
    with pytest.raises(ValidationError, match='voicing requires'):
        Arpeggiator.model_validate(
            {
                'bank': {'kind': kind},
                'rhythm': {'kind': 'grid', 'step': '1 beat'},
                'voicing': [0],
            }
        )
