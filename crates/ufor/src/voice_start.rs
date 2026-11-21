//! Portable pitch and stream identities for a selected voice start.

use crate::{error::Error, identifier::Identifier, quantity};
use sha2::{Digest, Sha256};

#[derive(Debug, PartialEq)]
pub struct VoiceStartValues {
    pub pitch_hz: Option<f64>,
    pub envelfo_key: u64,
    pub noise_key: Option<u64>,
}

/// Apply an authored offset to resolved pitch and derive the voice's stream keys.
pub fn prepare_values(
    seed: u64,
    voice_id: &Identifier,
    pitch_hz: Option<f64>,
    frequency_offset_hz: f64,
    noise: bool,
) -> Result<VoiceStartValues, Error> {
    let pitch_hz = pitch_hz
        .map(|pitch| quantity::finite(pitch + frequency_offset_hz))
        .transpose()?;
    Ok(VoiceStartValues {
        pitch_hz,
        envelfo_key: envelfo_stream_key(seed, voice_id.as_str()),
        noise_key: noise.then(|| noise_stream_key(seed, voice_id)),
    })
}

/// Resolve the stable key for an EnveLFO voice or graph identity.
pub fn envelfo_stream_key(seed: u64, identity: &str) -> u64 {
    stream_key(b"ufor-envelfo-v1\0", seed, identity)
}

/// Resolve the stable key for one noise voice.
pub fn noise_stream_key(seed: u64, voice_id: &Identifier) -> u64 {
    stream_key(b"ufor-noise-v1\0", seed, voice_id.as_str())
}

fn stream_key(domain: &[u8], seed: u64, identity: &str) -> u64 {
    let mut digest = Sha256::new();
    digest.update(domain);
    digest.update(seed.to_be_bytes());
    digest.update(identity.as_bytes());
    let bytes = digest.finalize();
    u64::from_be_bytes(bytes[..8].try_into().expect("eight digest bytes"))
}
