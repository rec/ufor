import json
from pathlib import Path

import pytest

from ufor.samples.variation import ResolvedVariation, Variation, resolve

CASES = json.loads(
    (Path(__file__).parents[1] / 'conformance/variation.json').read_text()
)


@pytest.mark.parametrize('case', CASES['cases'])
def test_variation_conformance(case: dict[str, object]) -> None:
    variation = Variation.model_validate(CASES['variation'])
    assert resolve(
        variation,
        int(CASES['seed']),
        str(case['part']),
        str(case['trigger_id']),
        int(case['tick']),
        int(case['ordinal']),
        str(case['identity']),
    ) == ResolvedVariation.model_validate(case['expected'])


def test_variation_is_independent_of_unrelated_voices() -> None:
    variation = Variation(delay_seconds=1, offset_frames=10, pitch_cents=20, gain_db=4)
    first = resolve(variation, 42, 'piano', 'note-a', 100, 3, 'take-a')
    resolve(variation, 42, 'drums', 'note-b', 100, 3, 'take-b')
    assert resolve(variation, 42, 'piano', 'note-a', 100, 3, 'take-a') == first
