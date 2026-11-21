use crate::error::Error;
use sha2::{Digest, Sha256};
use std::num::NonZeroU64;

pub(super) fn hash_field(digest: &mut Sha256, field: &str) {
    // Identifiers have a smaller portable length limit than the prefix.
    digest.update((field.len() as u32).to_be_bytes());
    digest.update(field.as_bytes());
}

pub(super) fn uniform_integer(digest: Sha256, bound: NonZeroU64) -> Result<u64, Error> {
    let bound = u128::from(bound.get());
    // Compute 2^256 modulo the bound one byte at a time.
    let rejected = (0..32).fold(1_u128, |value, _| (value << 8) % bound);
    for retry in 0..=u64::MAX {
        let mut draw = digest.clone();
        hash_field(&mut draw, &retry.to_string());
        let bytes = draw.finalize();
        // Only the last `rejected` integers of the 256-bit range are biased.
        if bytes[..24].iter().all(|byte| *byte == 255) {
            let tail = u64::from_be_bytes(bytes[24..].try_into().expect("eight digest bytes"));
            if u128::from(u64::MAX - tail) < rejected {
                continue;
            }
        }
        return Ok(bytes.iter().fold(0_u128, |value, byte| {
            ((value << 8) | u128::from(*byte)) % bound
        }) as u64);
    }
    Err(Error::Limit("sample draw retries"))
}
