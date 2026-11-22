//! Shared synth-family voice metadata and mapped event selection.

use crate::envelfo::PreparationLimits;
use crate::error::Error;
use crate::identifier::Identifier;
use crate::number::Rational;
use crate::quantity;
use crate::samples::eligibility::{Trigger, VoiceMapping};
use crate::samples::playback::Mapping;
use crate::samples::routing::ChannelRoute;
use crate::voice_admission::Choke;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use std::collections::BTreeSet;

#[derive(Debug, Deserialize, Serialize)]
#[serde(try_from = "VoiceDefinition")]
pub struct VoiceTemplate {
    #[serde(flatten)]
    voice: VoiceMapping,
    channels: Vec<ChannelRoute>,
    frequency_offset_hz: f64,
    #[serde(serialize_with = "write_seconds")]
    minimum_hold_seconds: Rational,
    choke_group: Option<Identifier>,
    chokes: Vec<Choke>,
    articulations: Vec<Identifier>,
}

impl VoiceTemplate {
    pub fn name(&self) -> &Identifier {
        &self.voice.name
    }

    pub fn mapping(&self) -> &Mapping {
        &self.voice.mapping
    }

    pub fn trigger(&self) -> Trigger {
        self.voice.trigger
    }

    pub fn channels(&self) -> &[ChannelRoute] {
        &self.channels
    }

    pub fn frequency_offset_hz(&self) -> f64 {
        self.frequency_offset_hz
    }

    pub fn minimum_hold_seconds(&self) -> Rational {
        self.minimum_hold_seconds
    }

    pub fn choke_group(&self) -> Option<&Identifier> {
        self.choke_group.as_ref()
    }

    pub fn chokes(&self) -> &[Choke] {
        &self.chokes
    }

    pub fn articulations(&self) -> &[Identifier] {
        &self.articulations
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct VoiceDefinition {
    name: Identifier,
    mapping: Mapping,
    #[serde(default)]
    trigger: Trigger,
    channels: Vec<ChannelRoute>,
    #[serde(default, deserialize_with = "hertz")]
    frequency_offset_hz: f64,
    #[serde(default = "zero", deserialize_with = "seconds")]
    minimum_hold_seconds: Rational,
    choke_group: Option<Identifier>,
    #[serde(default)]
    chokes: Vec<Choke>,
    #[serde(default)]
    articulations: Vec<Identifier>,
}

impl TryFrom<VoiceDefinition> for VoiceTemplate {
    type Error = Error;

    fn try_from(value: VoiceDefinition) -> Result<Self, Error> {
        let voice = VoiceMapping {
            name: value.name,
            mapping: value.mapping,
            trigger: value.trigger,
        };
        voice.validate()?;
        if value.channels.is_empty() {
            return Err(invalid("synth voice requires channel routes"));
        }
        let mut routes = BTreeSet::new();
        for route in &value.channels {
            if route.input.is_empty() || route.output.is_empty() || !route.gain.is_finite() {
                return Err(invalid("invalid synth voice channel route"));
            }
            if !routes.insert((&route.input, &route.output)) {
                return Err(invalid("duplicate channel route"));
            }
        }
        let articulations: BTreeSet<_> = value.articulations.iter().collect();
        if articulations.len() != value.articulations.len() {
            return Err(invalid("duplicate articulation reference"));
        }
        let chokes: BTreeSet<_> = value.chokes.iter().map(Choke::group).collect();
        if chokes.len() != value.chokes.len() {
            return Err(invalid("duplicate choke target"));
        }
        Ok(Self {
            voice,
            channels: value.channels,
            frequency_offset_hz: value.frequency_offset_hz,
            minimum_hold_seconds: value.minimum_hold_seconds,
            choke_group: value.choke_group,
            chokes: value.chokes,
            articulations: value.articulations,
        })
    }
}

/// Validated template metadata in instrument declaration order.
#[derive(Deserialize, Serialize)]
#[serde(try_from = "VoiceTemplatesDefinition")]
pub struct VoiceTemplates {
    voices: Vec<VoiceTemplate>,
}

impl VoiceTemplates {
    pub(crate) fn decode(
        value: serde_json::Value,
        limits: PreparationLimits,
    ) -> Result<Self, Error> {
        let templates: Self =
            serde_json::from_value(value).map_err(|error| Error::Invalid(error.to_string()))?;
        let records = 1 + templates
            .voices
            .iter()
            .map(|voice| 1 + voice.channels.len() + voice.chokes.len() + voice.articulations.len())
            .sum::<usize>();
        if records > limits.max_records() {
            return Err(Error::Limit("synth voice template records"));
        }
        Ok(templates)
    }

    pub fn voices(&self) -> &[VoiceTemplate] {
        &self.voices
    }

    pub fn matching_voices(
        &self,
        trigger: Trigger,
        key: i64,
        velocity: f64,
    ) -> impl Iterator<Item = &Identifier> {
        self.voices.iter().filter_map(move |voice| {
            voice
                .voice
                .matches(trigger, key, velocity)
                .then_some(voice.name())
        })
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct VoiceTemplatesDefinition {
    voices: Vec<VoiceTemplate>,
}

impl TryFrom<VoiceTemplatesDefinition> for VoiceTemplates {
    type Error = Error;

    fn try_from(value: VoiceTemplatesDefinition) -> Result<Self, Error> {
        if value.voices.is_empty() {
            return Err(invalid("synth instrument requires voices"));
        }
        let names: BTreeSet<_> = value.voices.iter().map(VoiceTemplate::name).collect();
        if names.len() != value.voices.len() {
            return Err(invalid("duplicate voice name"));
        }
        Ok(Self {
            voices: value.voices,
        })
    }
}

fn hertz<'de, D: Deserializer<'de>>(d: D) -> Result<f64, D::Error> {
    quantity::deserialize_scalar(d, "hz")
}

fn seconds<'de, D: Deserializer<'de>>(d: D) -> Result<Rational, D::Error> {
    let text = match serde_json::Value::deserialize(d)? {
        serde_json::Value::String(value) => value,
        serde_json::Value::Number(value) if value.is_i64() => value.to_string(),
        _ => {
            return Err(serde::de::Error::custom(
                "minimum hold requires exact seconds",
            ));
        }
    };
    let value = quantity::exact(&text, "seconds").map_err(serde::de::Error::custom)?;
    if value.numerator() < 0 {
        return Err(serde::de::Error::custom("minimum hold must be nonnegative"));
    }
    Ok(value)
}

fn write_seconds<S: Serializer>(value: &Rational, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.collect_str(value)
}

fn zero() -> Rational {
    0.into()
}

fn invalid(message: &str) -> Error {
    Error::Invalid(message.into())
}
