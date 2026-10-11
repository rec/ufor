"""Portable stream identities for independent Envelfo event gates."""

from hashlib import sha256


def stream_key(seed: int, identity: str) -> int:
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError('Envelfo seed must be an unsigned 64-bit integer')
    payload = b'ufor-envelfo-v1\0' + seed.to_bytes(8, 'big') + identity.encode('utf-8')
    return int.from_bytes(sha256(payload).digest()[:8], 'big')
