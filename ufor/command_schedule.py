"""Quantized command coordinates on an exact host tempo map."""

from collections.abc import Callable
from fractions import Fraction
from math import ceil

from .base import unique
from .control import TempoMap, TransportSeekError

ScheduleCommands = Callable[
    [TempoMap, int, list[tuple[int, int, Fraction | None]]],
    list[tuple[int, int, int]],
]


def schedule_commands(
    tempo_map: TempoMap,
    sample_rate: int,
    events: list[tuple[int, int, Fraction | None]],
) -> list[tuple[int, int, int]]:
    """Return original event indices with their scheduled ticks and ordinals."""
    if type(sample_rate) is not int or sample_rate <= 0:
        raise ValueError('sample rate must be positive')
    ordered = sorted(enumerate(events), key=lambda e: e[1][:2])
    unique(((t, o) for _, (t, o, _) in ordered), 'event coordinate')
    occupied = {t: o for _, (t, o, _) in ordered}
    scheduled: list[tuple[int, int, int]] = []
    for index, (tick, ordinal, division) in ordered:
        if division is not None:
            at = Fraction(tick, sample_rate)
            target = tempo_map.quantized_beat(at, division)
            try:
                dispatch = tempo_map.time_for_beat(target, at)
            except TransportSeekError:
                continue
            if dispatch is None:
                continue
            dispatch_tick = ceil(dispatch * sample_rate)
            if dispatch_tick != tick:
                tick = dispatch_tick
                ordinal = occupied.get(tick, -1) + 1
                occupied[tick] = ordinal
        scheduled.append((index, tick, ordinal))
    return sorted(scheduled, key=lambda e: e[1:])
