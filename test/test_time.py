import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.time import Rate, TickRange, Timebase, convert_tick


@pytest.mark.parametrize(
    ('tick', 'source_rate', 'destination_rate', 'expected'),
    json.loads(
        (Path(__file__).parents[1] / 'conformance/physical-time.json').read_text()
    ),
)
def test_positions_convert_once_with_even_ties(
    tick: int, source_rate: list[int], destination_rate: list[int], expected: int
) -> None:
    source = Timebase(
        name='source', rate=Rate(numerator=source_rate[0], denominator=source_rate[1])
    )
    destination = Timebase(
        name='destination',
        rate=Rate(numerator=destination_rate[0], denominator=destination_rate[1]),
    )
    assert convert_tick(tick, source, destination) == expected


@pytest.mark.parametrize('value', [0, -1, True, 1.5])
def test_rates_reject_nonpositive_or_noninteger_values(value: object) -> None:
    with pytest.raises(ValidationError):
        Rate.model_validate({'numerator': value})


def test_ranges_are_nonempty_and_allow_preroll() -> None:
    assert TickRange(start=-1, end=0).start == -1
    with pytest.raises(ValidationError):
        TickRange(start=1, end=1)
