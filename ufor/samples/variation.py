"""Deterministic per-voice sample variation."""

from hashlib import sha256

from pydantic import Field

from ..base import Frame, Identifier, Model, Seconds


class Variation(Model):
    """Maximum independent variation applied when one voice starts."""

    delay_seconds: Seconds = 0
    offset_frames: Frame = 0
    pitch_cents: float = Field(default=0, strict=True, ge=0)
    gain_db: float = Field(default=0, strict=True, ge=0)


class ResolvedVariation(Model):
    delay_seconds: Seconds = 0
    offset_frames: Frame = 0
    pitch_cents: float = Field(default=0, strict=True)
    gain_db: float = Field(default=0, strict=True)


def resolve(
    variation: Variation,
    seed: int,
    part: Identifier,
    trigger_id: Identifier | None,
    tick: int,
    ordinal: int,
    identity: Identifier,
) -> ResolvedVariation:
    """Resolve one stateless, block-independent variation draw."""
    values = (str(seed), part, trigger_id or '', str(tick), str(ordinal), identity)
    return ResolvedVariation(
        delay_seconds=variation.delay_seconds
        * _unit_interval(*values, 'delay_seconds'),
        offset_frames=_integer(variation.offset_frames + 1, *values, 'offset_frames'),
        pitch_cents=variation.pitch_cents
        * (2 * _unit_interval(*values, 'pitch_cents') - 1),
        gain_db=variation.gain_db * (2 * _unit_interval(*values, 'gain_db') - 1),
    )


def _unit_interval(*values: str) -> float:
    return (_digest(*values) >> 203) / (1 << 53)


def _integer(bound: int, *values: str) -> int:
    limit = 1 << 256
    retry = 0
    while True:
        value = _digest(*values, str(retry))
        acceptable = limit - limit % bound
        if value < acceptable:
            return value % bound
        retry += 1


def _digest(*values: str) -> int:
    digest = sha256()
    for value in ('sample-variation-v1', *values):
        encoded = value.encode()
        digest.update(len(encoded).to_bytes(4, 'big'))
        digest.update(encoded)
    return int.from_bytes(digest.digest(), 'big')
