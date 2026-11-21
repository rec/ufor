"""Portable pitch and stream identities for a selected voice start."""

from collections.abc import Callable
from math import isfinite

from . import envelfo_random, noise
from .base import Identifier

PrepareVoiceStart = Callable[
    [int, Identifier, float | None, float, bool], tuple[float | None, int, int | None]
]


def prepare_values(
    seed: int,
    voice_id: Identifier,
    pitch_hz: float | None,
    frequency_offset_hz: float,
    is_noise: bool,
) -> tuple[float | None, int, int | None]:
    """Return resolved pitch, the EnveLFO key, and the optional noise key."""
    pitch = pitch_hz + frequency_offset_hz if pitch_hz is not None else None
    if pitch is not None and not isfinite(pitch):
        raise ValueError('voice start pitch must be finite')
    return (
        pitch,
        envelfo_random.stream_key(seed, voice_id),
        noise.stream_key(seed, voice_id) if is_noise else None,
    )
