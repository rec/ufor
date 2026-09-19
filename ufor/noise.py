"""Portable noise stream identity; audio generation belongs to engines."""

from hashlib import sha256

from .base import identifier


def stream_key(seed: int, voice_id: str) -> int:
    """Resolve noise-v1 identity without depending on host hashing or RNG state."""
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError('Noise seed must be an unsigned 64-bit integer')
    identifier(voice_id)
    payload = b'ufor-noise-v1\0' + seed.to_bytes(8, 'big') + voice_id.encode('utf-8')
    return int.from_bytes(sha256(payload).digest()[:8], 'big')
