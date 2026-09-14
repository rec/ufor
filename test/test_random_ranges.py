import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.samples.selection import RandomRange, random_range_value

CASES = json.loads(
    (Path(__file__).parents[1] / 'conformance/random-ranges.json').read_text()
)


@pytest.mark.parametrize('case', CASES['cases'])
def test_random_range_conformance(case: dict[str, object]) -> None:
    assert (
        random_range_value(
            int(CASES['seed']),
            str(case['part']),
            str(case['trigger_id']),
            int(case['tick']),
            int(case['ordinal']),
        )
        == case['expected']
    )


def test_random_range_is_half_open_and_nonempty() -> None:
    value = RandomRange(minimum=0.25, maximum=0.5)
    assert value.contains(0.25)
    assert not value.contains(0.5)
    with pytest.raises(ValidationError, match='must not be empty'):
        RandomRange(minimum=0.5, maximum=0.5)
