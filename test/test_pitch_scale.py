import pytest
from pydantic import ValidationError

from ufor.arpeggiator import Arpeggiator, ScaleMapping, ScaleTransform
from ufor.scale import Scale


def test_scale_transform_reuses_generalized_scale() -> None:
    transform = ScaleTransform(definition=Scale(notes='CDEFGAB'))
    assert transform.definition.note_numbers == (0, 2, 4, 5, 7, 9, 11)
    assert transform.mapping == ScaleMapping.nearest
    assert transform.degrees == 0
    assert ScaleTransform.model_validate_json(transform.model_dump_json()) == transform


@pytest.mark.parametrize(
    'fields',
    [
        {'definition': {'intervals': [0]}},
        {'degrees': True},
        {'degrees': 2**63},
        {'mapping': 'preserve'},
        {'root': 0, 'intervals': [0, 2, 4]},
    ],
)
def test_scale_transform_rejects_invalid_or_old_definitions(
    fields: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ScaleTransform.model_validate({'definition': {}, **fields})


@pytest.mark.parametrize(
    'source',
    [
        {'kind': 'frequencies', 'values': ['440']},
        {'kind': 'ratios', 'values': ['1']},
        {'kind': 'intervals', 'intervals': ['3/2'], 'repeat': False},
    ],
)
def test_finite_tunings_reject_period_transforms(source: dict[str, object]) -> None:
    settings = {
        'rhythm': {'kind': 'grid', 'step': '1 beat'},
        'tuning': {'source': source},
        'bend_range': 2,
    }
    assert Arpeggiator.model_validate(settings).tuning is not None
    for transform in [
        {'inversion': 1},
        {'voicing': [1]},
        {'octaves': {'offsets': [1]}},
        {'transposition': {'boundary': 'fold'}},
    ]:
        with pytest.raises(ValidationError, match='finite tunings'):
            Arpeggiator.model_validate({**settings, **transform})


def test_tuning_requires_explicit_bend_range() -> None:
    with pytest.raises(ValidationError, match='bend_range'):
        Arpeggiator.model_validate(
            {
                'rhythm': {'kind': 'grid', 'step': '1 beat'},
                'tuning': {'source': {'kind': 'computed'}},
            }
        )
