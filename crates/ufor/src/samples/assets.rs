//! Resolve declared sample extents and timebases before using decoded audio.

use super::{playback::Slice, routing::check_layout};
use crate::{
    envelfo::PreparationLimits,
    error::Error,
    identifier::Identifier,
    time::{Rate, Timebase},
};
use serde::Deserialize;
use std::collections::{BTreeMap, BTreeSet};

/// Validated playback metadata for the output and all referenced assets.
pub struct Inventory {
    output_rate: Rate,
    required: BTreeMap<String, AssetExtent>,
}

impl Inventory {
    pub(crate) fn decode(
        value: serde_json::Value,
        limits: PreparationLimits,
    ) -> Result<Self, Error> {
        let authored: Declaration =
            serde_json::from_value(value).map_err(|error| invalid(error.to_string()))?;
        let records = 1 + authored.timebases.len() + authored.assets.len() + authored.slices.len();
        if records > limits.max_records() {
            return Err(Error::Limit("sample inventory records"));
        }
        if authored.assets.is_empty() || authored.slices.is_empty() {
            return Err(invalid("Sample inventory requires assets and slices"));
        }
        check_layout(&authored.output.channels)?;
        let mut rates = BTreeMap::new();
        for timebase in &authored.timebases {
            if rates.insert(timebase.name(), timebase.rate()).is_some() {
                return Err(invalid("Duplicate timebase name"));
            }
        }
        let output_rate = *rates
            .get(&authored.output.timebase)
            .ok_or_else(|| invalid("Unknown audio timebase"))?;

        let mut assets = BTreeMap::new();
        for asset in &authored.assets {
            check_layout(&asset.audio.channels)?;
            let rate = *rates
                .get(&asset.audio.timebase)
                .ok_or_else(|| invalid("Unknown audio timebase"))?;
            if asset.audio.frames < 0 {
                return Err(invalid("Audio frame count must be nonnegative"));
            }
            let extent = AssetExtent {
                rate,
                frames: asset.audio.frames,
                channels: asset.audio.channels.len(),
            };
            if assets.insert(&asset.name, extent).is_some() {
                return Err(invalid("Duplicate asset ID"));
            }
        }

        let mut slice_names = BTreeSet::new();
        let mut required = BTreeMap::new();
        for slice in &authored.slices {
            if !slice_names.insert(slice.name()) {
                return Err(invalid("Duplicate sample slice name"));
            }
            let extent = *assets.get(slice.asset()).ok_or_else(|| {
                invalid(format!("Unknown slice asset: {}", slice.asset().as_str()))
            })?;
            if slice.end_frame() > extent.frames {
                return Err(invalid("Slice exceeds native asset frames"));
            }
            required.insert(slice.asset().as_str().to_owned(), extent);
        }
        Ok(Self {
            output_rate,
            required,
        })
    }

    /// Validate decoded shapes and return the rates for integer-rate playback.
    ///
    /// The decoded inventory must contain exactly the assets named by slices.
    /// Rates keep their declared denominator, even when reducible to an integer.
    pub fn integer_rates(
        &self,
        decoded_shapes: &BTreeMap<String, Vec<usize>>,
    ) -> Result<(i64, BTreeMap<String, i64>), Error> {
        let output_rate = self
            .output_rate
            .integer_hz()
            .ok_or_else(|| invalid("Sampler output rate must be an integer"))?;
        if !self.required.keys().eq(decoded_shapes.keys()) {
            return Err(invalid(
                "Decoded assets must match the referenced asset IDs",
            ));
        }
        let mut native_rates = BTreeMap::new();
        for (name, extent) in &self.required {
            let shape = decoded_shapes[name].as_slice();
            if !matches!(shape, [frames, channels] if i64::try_from(*frames) == Ok(extent.frames) && *channels == extent.channels)
            {
                return Err(invalid(format!(
                    "Decoded asset {name} does not match its frame/channel layout"
                )));
            }
            let rate = extent
                .rate
                .integer_hz()
                .ok_or_else(|| invalid("Sampler native rate must be an integer"))?;
            native_rates.insert(name.clone(), rate);
        }
        Ok((output_rate, native_rates))
    }
}

#[derive(Clone, Copy)]
struct AssetExtent {
    rate: Rate,
    frames: i64,
    channels: usize,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AudioLayout {
    timebase: Identifier,
    channels: Vec<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AudioDescription {
    timebase: Identifier,
    channels: Vec<String>,
    frames: i64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Asset {
    name: Identifier,
    audio: AudioDescription,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Declaration {
    timebases: Vec<Timebase>,
    assets: Vec<Asset>,
    slices: Vec<Slice>,
    output: AudioLayout,
}

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
