//! Stateless sample draws tied to a performance event and, for variation, a take.

use super::random::{hash_field, uniform_integer};
use crate::{error::Error, identifier::Identifier};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::num::NonZeroU64;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DrawEvent {
    pub seed: u64,
    pub part: Identifier,
    pub trigger_id: Option<Identifier>,
    pub tick: i64,
    pub ordinal: u64,
}

impl DrawEvent {
    /// One shared draw for all random-range conditions at this event.
    pub fn random_range_value(&self) -> f64 {
        let bytes = self.digest("sample-random-range-v1").finalize();
        let prefix = u64::from_be_bytes(bytes[..8].try_into().expect("eight digest bytes"));
        (prefix >> 8) as f64 / (1_u64 << 56) as f64
    }

    fn digest(&self, domain: &str) -> Sha256 {
        let mut digest = Sha256::new();
        for field in [
            domain,
            &self.seed.to_string(),
            self.part.as_str(),
            self.trigger_id.as_ref().map_or("", Identifier::as_str),
            &self.tick.to_string(),
            &self.ordinal.to_string(),
        ] {
            hash_field(&mut digest, field);
        }
        digest
    }
}

/// Canonical variation bounds in seconds, sample frames, cents and decibels.
#[derive(Debug, Default, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Variation {
    pub delay_seconds: f64,
    pub offset_frames: i64,
    pub pitch_cents: f64,
    pub gain_db: f64,
}

#[derive(Debug, PartialEq, Serialize)]
pub struct ResolvedVariation {
    pub delay_seconds: f64,
    pub offset_frames: i64,
    pub pitch_cents: f64,
    pub gain_db: f64,
}

impl Variation {
    /// Resolve independent draws for the supplied take or slot identity.
    pub fn resolve(
        &self,
        event: &DrawEvent,
        identity: &Identifier,
    ) -> Result<ResolvedVariation, Error> {
        if self.offset_frames < 0
            || [self.delay_seconds, self.pitch_cents, self.gain_db]
                .iter()
                .any(|value| !value.is_finite() || *value < 0.0)
        {
            return Err(Error::Invalid(
                "sample variation bounds must be finite and nonnegative".into(),
            ));
        }
        let mut digest = event.digest("sample-variation-v1");
        hash_field(&mut digest, identity.as_str());
        let mut offset = digest.clone();
        hash_field(&mut offset, "offset_frames");
        let bound = NonZeroU64::new(self.offset_frames as u64 + 1).expect("positive offset bound");
        Ok(ResolvedVariation {
            delay_seconds: self.delay_seconds * unit_interval(&digest, "delay_seconds"),
            offset_frames: uniform_integer(offset, bound)? as i64,
            pitch_cents: self.pitch_cents * (2.0 * unit_interval(&digest, "pitch_cents") - 1.0),
            gain_db: self.gain_db * (2.0 * unit_interval(&digest, "gain_db") - 1.0),
        })
    }
}

fn unit_interval(digest: &Sha256, parameter: &str) -> f64 {
    let mut draw = digest.clone();
    hash_field(&mut draw, parameter);
    let bytes = draw.finalize();
    let prefix = u64::from_be_bytes(bytes[..8].try_into().expect("eight digest bytes"));
    (prefix >> 11) as f64 / (1_u64 << 53) as f64
}
