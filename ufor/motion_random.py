"""Portable identities and SplitMix64 words for independent Motion event gates."""

from hashlib import sha256


def stream_key(seed: int, identity: str) -> int:
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError('Motion seed must be an unsigned 64-bit integer')
    payload = b'ufor-motion-v1\0' + seed.to_bytes(8, 'big') + identity.encode('utf-8')
    return int.from_bytes(sha256(payload).digest()[:8], 'big')


def random_word(state: int) -> tuple[int, int]:
    state = (state + 0x9E3779B97F4A7C15) & 0xFFFF_FFFF_FFFF_FFFF
    word = ((state ^ (state >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFF_FFFF_FFFF_FFFF
    word = ((word ^ (word >> 27)) * 0x94D049BB133111EB) & 0xFFFF_FFFF_FFFF_FFFF
    return state, word ^ (word >> 31)
