import json
from fractions import Fraction
from pathlib import Path

import pytest

from ufor.envelope import Curve, curve_at


def test_shared_envelope_curves() -> None:
    source = Path(__file__).parents[1] / 'conformance' / 'envelope-curves.json'
    with source.open() as stream:
        cases = json.load(stream)['cases']
    for case in cases:
        curve = Curve.model_validate(case['curve'])
        for query in case['queries']:
            assert curve_at(curve, Fraction(query['at'])) == pytest.approx(
                query['value'], rel=0, abs=1e-14
            ), case['name']
