//! Yamaha voice controls and TX81Z instrument routing declarations.

use super::{SynthVoices, VoiceSource, invalid, present_value};
use crate::error::Error;
use crate::identifier::Identifier;
use crate::samples::processing::{FilterOrder, Processing};
use crate::samples::routing::ChannelRoute;
use crate::yamaha::Patch;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct Dx7ControllerAssignment {
    #[serde(deserialize_with = "controller_range")]
    pub range: u8,
    pub pitch: bool,
    pub amplitude: bool,
    pub eg_bias: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct Dx7Performance {
    #[serde(deserialize_with = "bend_range")]
    pub pitch_bend_range: u8,
    pub modulation_wheel: Dx7ControllerAssignment,
    pub breath: Dx7ControllerAssignment,
    pub foot: Dx7ControllerAssignment,
}

impl Default for Dx7Performance {
    fn default() -> Self {
        Self {
            pitch_bend_range: 2,
            modulation_wheel: Dx7ControllerAssignment::default(),
            breath: Dx7ControllerAssignment::default(),
            foot: Dx7ControllerAssignment::default(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Tx81zOutput {
    name: Identifier,
    voices: Vec<Identifier>,
    channels: Vec<ChannelRoute>,
    #[serde(default)]
    processing: Processing,
}

impl Tx81zOutput {
    pub fn name(&self) -> &Identifier {
        &self.name
    }

    pub fn voices(&self) -> &[Identifier] {
        &self.voices
    }

    pub fn channels(&self) -> &[ChannelRoute] {
        &self.channels
    }

    pub fn processing(&self) -> &Processing {
        &self.processing
    }

    pub(super) fn records(&self) -> usize {
        2 + self.voices.len() + self.channels.len() + self.processing.filters().len()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Tx81zLfoSelection {
    Off,
    First,
    Second,
    Vibrato,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Tx81zLfoGroup {
    name: Identifier,
    first: Identifier,
    #[serde(skip_serializing_if = "Option::is_none")]
    second: Option<Identifier>,
    routes: BTreeMap<Identifier, Tx81zLfoSelection>,
}

impl Tx81zLfoGroup {
    pub fn name(&self) -> &Identifier {
        &self.name
    }

    pub fn first(&self) -> &Identifier {
        &self.first
    }

    pub fn second(&self) -> Option<&Identifier> {
        self.second.as_ref()
    }

    pub fn routes(&self) -> &BTreeMap<Identifier, Tx81zLfoSelection> {
        &self.routes
    }

    pub(super) fn records(&self) -> usize {
        1 + self.routes.len()
    }
}

#[derive(Deserialize)]
pub(super) struct YamahaWire {
    #[serde(default, deserialize_with = "present_value")]
    yamaha: Option<Value>,
    #[serde(default, deserialize_with = "present_value")]
    patch: Option<Value>,
    #[serde(default, deserialize_with = "present_value")]
    additional: Option<Value>,
    #[serde(default, deserialize_with = "present_value")]
    additional2: Option<Value>,
    #[serde(default, deserialize_with = "present_value")]
    performance: Option<Value>,
}

impl YamahaWire {
    pub(super) fn prepare(self) -> Result<Option<(Patch, Option<Dx7Performance>)>, Error> {
        let fields = [
            ("yamaha", self.yamaha),
            ("patch", self.patch),
            ("additional", self.additional),
            ("additional2", self.additional2),
        ];
        let values: Map<_, _> = fields
            .into_iter()
            .filter_map(|(name, value)| value.map(|value| (name.into(), value)))
            .collect();
        if values.is_empty() && self.performance.is_none() {
            return Ok(None);
        }
        let patch = serde_json::from_value(Value::Object(values))
            .map_err(|error| invalid(error.to_string()))?;
        let performance = if matches!(patch, Patch::Dx7(_)) {
            Some(
                self.performance
                    .map_or(Ok(Dx7Performance::default()), serde_json::from_value)
                    .map_err(|error| invalid(error.to_string()))?,
            )
        } else if self.performance.is_some() {
            return Err(invalid("DX7 performance settings require a DX7 patch"));
        } else {
            None
        };
        Ok(Some((patch, performance)))
    }
}

pub(super) fn validate_routing(
    voices: &SynthVoices,
    outputs: &[Tx81zOutput],
    groups: &[Tx81zLfoGroup],
) -> Result<(), Error> {
    let templates: BTreeMap<_, _> = voices
        .voices()
        .iter()
        .map(|voice| (voice.template().name(), voice))
        .collect();
    let is_tx81z = |name| {
        templates.get(name).filter(|voice| {
            matches!(
                voice.source(),
                VoiceSource::Yamaha {
                    patch: Patch::Tx81z(_),
                    ..
                }
            )
        })
    };
    let mut group_names = BTreeSet::new();
    let mut lfo_members = BTreeSet::new();
    for group in groups {
        if !group_names.insert(&group.name) {
            return Err(invalid("duplicate TX81Z LFO group ID"));
        }
        if group.second.as_ref() == Some(&group.first) {
            return Err(invalid("TX81Z LFO owners must be distinct"));
        }
        if !group.routes.contains_key(&group.first)
            || group
                .second
                .as_ref()
                .is_some_and(|owner| !group.routes.contains_key(owner))
        {
            return Err(invalid("TX81Z LFO owners must be group members"));
        }
        for (name, selection) in &group.routes {
            if !lfo_members.insert(name) {
                return Err(invalid("duplicate TX81Z LFO membership"));
            }
            if is_tx81z(name).is_none() {
                return Err(invalid("TX81Z LFO groups require existing TX81Z templates"));
            }
            if group.second.is_none() && *selection == Tx81zLfoSelection::Second {
                return Err(invalid("TX81Z second LFO routing requires an owner"));
            }
        }
    }
    let mut output_names = BTreeSet::new();
    let mut output_members = BTreeSet::new();
    for output in outputs {
        if !output_names.insert(&output.name) {
            return Err(invalid("duplicate TX81Z output ID"));
        }
        if output.voices.is_empty() || output.channels.is_empty() {
            return Err(invalid("TX81Z outputs require voices and channel routes"));
        }
        super::validate_channel_routes(&output.channels)?;
        let processing = &output.processing;
        if processing.tuning_cents() != 0.0
            || processing.pan() != 0.0
            || processing.stereo_balance() != 0.0
            || !processing.equalizer().is_empty()
        {
            return Err(invalid(
                "TX81Z output processing supports gain and filters only",
            ));
        }
        for name in &output.voices {
            if !output_members.insert(name) {
                return Err(invalid("duplicate TX81Z output membership"));
            }
            let voice = is_tx81z(name)
                .ok_or_else(|| invalid("TX81Z outputs require existing TX81Z templates"))?;
            if !voice.template().channels().is_empty() {
                return Err(invalid("Grouped TX81Z voices must omit individual routes"));
            }
            let processing = voice.settings().processing();
            if processing.volume_db() != 0.0
                || processing.invert_polarity()
                || processing.pan() != 0.0
                || processing.stereo_balance() != 0.0
                || !processing.equalizer().is_empty()
                || !processing.filters().is_empty()
                || processing.filter_order() != FilterOrder::default()
                || voice
                    .settings()
                    .modulation()
                    .parameters()
                    .iter()
                    .any(|parameter| {
                        let target = parameter.target();
                        target.name().as_str() != "yamaha"
                            && (target.name().as_str(), target.parameter().as_str())
                                != ("processing", "tuning_cents")
                    })
            {
                return Err(invalid(
                    "Grouped TX81Z voices allow tuning and Yamaha controls only",
                ));
            }
        }
    }
    if voices.voices().iter().any(|voice| {
        let template = voice.template();
        template.channels().is_empty() && !output_members.contains(template.name())
    }) {
        return Err(invalid("Unrouted TX81Z voices require output membership"));
    }
    Ok(())
}

fn controller_range<'de, D: serde::Deserializer<'de>>(decoder: D) -> Result<u8, D::Error> {
    let value = u8::deserialize(decoder)?;
    if value > 99 {
        return Err(serde::de::Error::custom(
            "DX7 controller range must be from 0 through 99",
        ));
    }
    Ok(value)
}

fn bend_range<'de, D: serde::Deserializer<'de>>(decoder: D) -> Result<u8, D::Error> {
    let value = u8::deserialize(decoder)?;
    if value > 12 {
        return Err(serde::de::Error::custom(
            "DX7 pitch bend range must be from 0 through 12",
        ));
    }
    Ok(value)
}
