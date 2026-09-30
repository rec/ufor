from fractions import Fraction

import pytest
from pydantic import ValidationError

from ufor.control import TempoMap


def test_host_tempo_map_preserves_exact_beats_through_tempo_stop_and_seek() -> None:
    clock = TempoMap.model_validate(
        {
            'points': [
                {'at_seconds': '0', 'beat': '0', 'bpm': '120'},
                {'at_seconds': '1', 'beat': '2', 'bpm': '60'},
                {'at_seconds': '2', 'beat': '3', 'bpm': '60', 'running': False},
                {'at_seconds': '3', 'beat': '8', 'bpm': '90'},
            ]
        }
    )
    assert [clock.beat_at(Fraction(n, 2)) for n in range(9)] == [
        Fraction(0),
        Fraction(1),
        Fraction(2),
        Fraction(5, 2),
        Fraction(3),
        Fraction(3),
        Fraction(8),
        Fraction(35, 4),
        Fraction(19, 2),
    ]
    restored = TempoMap.model_validate_json(clock.model_dump_json())
    assert restored.beat_at(Fraction(7, 2)) == Fraction(35, 4)


def test_host_tempo_map_rejects_ambiguous_ordering_and_nonpositive_rate() -> None:
    for points in (
        [{'at_seconds': '1', 'beat': '0', 'bpm': '120'}],
        [
            {'at_seconds': '0', 'beat': '0', 'bpm': '120'},
            {'at_seconds': '0', 'beat': '2', 'bpm': '60'},
        ],
        [{'at_seconds': '0', 'beat': '0', 'bpm': '0'}],
    ):
        with pytest.raises(ValidationError):
            TempoMap.model_validate({'points': points})
    with pytest.raises(ValueError, match='nonnegative'):
        TempoMap.model_validate(
            {'points': [{'at_seconds': '0', 'beat': '0', 'bpm': '120'}]}
        ).beat_at(Fraction(-1))
