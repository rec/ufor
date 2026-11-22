//! Resolve declared sample extents and timebases before using decoded audio.

use super::{
    playback::Slice,
    routing::{ChannelRoute, check_layout},
    slots::Kind,
};
use crate::{
    envelfo::PreparationLimits,
    error::Error,
    identifier::Identifier,
    musical::header,
    synth::score::{AudioOutput, PerformanceInput, validate_instrument_ports},
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
        Self::prepare(authored, &[], limits)
    }

    pub(crate) fn decode_score(
        value: serde_json::Value,
        limits: PreparationLimits,
    ) -> Result<Self, Error> {
        let authored: ScoreInventory =
            serde_json::from_value(value).map_err(|error| invalid(error.to_string()))?;
        if authored.format != "recs" || authored.version != 4 || authored.kind != "instrument" {
            return Err(invalid("expected a recs version 4 sample instrument score"));
        }
        header(&authored.name, &authored.title, authored.tags)?;
        if authored.body.slots.is_empty() {
            return Err(invalid("sample instrument requires at least one slot"));
        }
        let [input] = authored.inputs;
        let [output] = authored.outputs;
        validate_instrument_ports(&authored.timebases, &input, &output)?;
        let mut assets = Vec::with_capacity(authored.assets.len());
        for asset in authored.assets {
            match asset.location {
                Location::RelativeFile
                | Location::VolumeFile
                | Location::Download
                | Location::GitFile
                | Location::PythonProvider {
                    delivery: Delivery::Buffer,
                } => {}
                _ => {
                    return Err(invalid(
                        "sample instruments require finite, seekable assets",
                    ));
                }
            }
            assets.push(Asset {
                name: asset.name,
                audio: asset.audio,
            });
        }
        Self::prepare(
            Declaration {
                timebases: authored.timebases,
                assets,
                slices: authored.body.slices,
                output: AudioLayout {
                    timebase: output.stream.timebase,
                    channels: output.stream.channels,
                },
            },
            &authored.body.slots,
            limits,
        )
    }

    fn prepare(
        authored: Declaration,
        slots: &[SlotRoute],
        limits: PreparationLimits,
    ) -> Result<Self, Error> {
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
            if assets
                .insert(&asset.name, (extent, asset.audio.channels.as_slice()))
                .is_some()
            {
                return Err(invalid("Duplicate asset ID"));
            }
        }

        let mut slices = BTreeMap::new();
        let mut required = BTreeMap::new();
        for slice in &authored.slices {
            if slices.insert(slice.name(), slice.asset()).is_some() {
                return Err(invalid("Duplicate sample slice name"));
            }
            let (extent, _) = *assets.get(slice.asset()).ok_or_else(|| {
                invalid(format!("Unknown slice asset: {}", slice.asset().as_str()))
            })?;
            if slice.end_frame() > extent.frames {
                return Err(invalid("Slice exceeds native asset frames"));
            }
            required.insert(slice.asset().as_str().to_owned(), extent);
        }
        for slot in slots {
            let asset = slices
                .get(&slot.slice)
                .ok_or_else(|| invalid(format!("Unknown slice: {}", slot.slice.as_str())))?;
            let (_, channels) = assets[asset];
            let mut routes = BTreeSet::new();
            if slot.channels.is_empty() {
                return Err(invalid("sample slot requires channel routes"));
            }
            for route in &slot.channels {
                if !channels.contains(&route.input)
                    || !authored.output.channels.contains(&route.output)
                {
                    return Err(invalid("Unknown channel in slot channel map"));
                }
                if !routes.insert((&route.input, &route.output)) {
                    return Err(invalid("duplicate slot channel route"));
                }
            }
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

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ScoreInventory {
    format: String,
    version: i64,
    kind: String,
    name: String,
    title: String,
    #[serde(default)]
    tags: Vec<String>,
    #[serde(default, rename = "description")]
    _description: Option<String>,
    #[serde(default, rename = "parameters")]
    _parameters: Vec<serde_json::Value>,
    timebases: Vec<Timebase>,
    inputs: [PerformanceInput; 1],
    outputs: [AudioOutput; 1],
    assets: Vec<ScoreAsset>,
    body: ScoreBody,
}

#[derive(Deserialize)]
struct ScoreAsset {
    name: Identifier,
    location: Location,
    audio: AudioDescription,
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum Location {
    RelativeFile,
    VolumeFile,
    Download,
    GitFile,
    Stream,
    PythonProvider { delivery: Delivery },
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum Delivery {
    Buffer,
    Callback,
    ClientBuffer,
}

#[derive(Deserialize)]
struct ScoreBody {
    #[serde(default, rename = "kind")]
    _kind: Kind,
    slices: Vec<Slice>,
    slots: Vec<SlotRoute>,
}

#[derive(Deserialize)]
struct SlotRoute {
    slice: Identifier,
    channels: Vec<ChannelRoute>,
}

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
