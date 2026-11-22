//! Shared synth-family voice metadata and mapped event selection.

use crate::control::{Polarity, Scope};
use crate::envelfo::wire::RootWire;
use crate::envelfo::{self, Body, Generator, PreparationLimits};
use crate::error::Error;
use crate::fm::Fm;
use crate::identifier::Identifier;
use crate::number::Rational;
use crate::oscillator::Oscillator;
use crate::quantity;
use crate::samples::eligibility::{Trigger, VoiceMapping};
use crate::samples::playback::Mapping;
use crate::samples::routing::ChannelRoute;
use crate::voice_admission::Choke;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::{Value, json};
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

    fn records(&self) -> usize {
        1 + self.channels.len() + self.chokes.len() + self.articulations.len()
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
            .map(VoiceTemplate::records)
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
        validate_names(value.voices.iter().map(VoiceTemplate::name))?;
        Ok(Self {
            voices: value.voices,
        })
    }
}

/// One mapped voice with its source and main amplitude definition.
#[derive(Debug, Serialize)]
pub struct SynthVoice {
    #[serde(flatten)]
    template: VoiceTemplate,
    #[serde(flatten)]
    source: VoiceSource,
}

impl SynthVoice {
    pub fn template(&self) -> &VoiceTemplate {
        &self.template
    }

    pub fn source(&self) -> &VoiceSource {
        &self.source
    }
}

#[derive(Debug, Serialize)]
#[serde(untagged)]
pub enum VoiceSource {
    Oscillator {
        oscillator: Oscillator,
        synchronize_oscillator: bool,
        envelope: Generator,
    },
    Noise {
        noise: NoiseKind,
        envelope: Generator,
    },
    Fm {
        fm: Fm,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NoiseKind {
    White,
}

/// Synth-family source projections in instrument declaration order.
#[derive(Debug, Serialize)]
pub struct SynthVoices {
    voices: Vec<SynthVoice>,
}

impl SynthVoices {
    pub(crate) fn decode(value: Value, limits: PreparationLimits) -> Result<Self, Error> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Definition {
            voices: Vec<Value>,
        }

        let definition: Definition =
            serde_json::from_value(value).map_err(|error| invalid(error.to_string()))?;
        let mut records = 1;
        limits.check_records(records)?;
        let mut voices = Vec::new();
        for value in definition.voices {
            let Value::Object(mut fields) = value else {
                return Err(invalid("expected a synth voice object"));
            };
            let oscillator = fields.remove("oscillator");
            let sync = fields.remove("synchronize_oscillator");
            let noise = fields.remove("noise");
            let fm = fields.remove("fm");
            let envelope = fields.remove("envelope");
            let template: VoiceTemplate = serde_json::from_value(Value::Object(fields))
                .map_err(|error| invalid(error.to_string()))?;
            records += template.records();
            if records > limits.max_records() {
                return Err(Error::Limit("synth voice template records"));
            }
            let remaining = PreparationLimits::new(limits.max_records() - records)?;
            let (source, source_records) = match (oscillator, noise, fm) {
                (Some(oscillator), None, None) => {
                    let oscillator = serde_json::from_value(oscillator)
                        .map_err(|error| invalid(error.to_string()))?;
                    let synchronize_oscillator = sync
                        .map_or(Ok(false), serde_json::from_value)
                        .map_err(|error| invalid(error.to_string()))?;
                    let (envelope, count) = amplitude_envelope(envelope, remaining)?;
                    (
                        VoiceSource::Oscillator {
                            oscillator,
                            synchronize_oscillator,
                            envelope,
                        },
                        count + 1,
                    )
                }
                (None, Some(noise), None) if sync.is_none() => {
                    let noise = serde_json::from_value(noise)
                        .map_err(|error| invalid(error.to_string()))?;
                    if template.mapping().pitch_tracking() || template.frequency_offset_hz() != 0.0
                    {
                        return Err(invalid("noise does not support pitch tracking or offsets"));
                    }
                    let (envelope, count) = amplitude_envelope(envelope, remaining)?;
                    (VoiceSource::Noise { noise, envelope }, count + 1)
                }
                (None, None, Some(fm)) if sync.is_none() => {
                    if envelope.is_some_and(|envelope| !envelope.is_null()) {
                        return Err(invalid(
                            "FM uses operator envelopes, not a second amplitude envelope",
                        ));
                    }
                    let count = envelfo::preparation_records(&fm, remaining)?;
                    let fm =
                        Fm::decode(fm, remaining).map_err(|error| invalid(error.to_string()))?;
                    (VoiceSource::Fm { fm }, count)
                }
                _ => {
                    return Err(invalid(
                        "synth voice requires exactly one oscillator, noise or FM source",
                    ));
                }
            };
            records += source_records;
            limits.check_records(records)?;
            voices.push(SynthVoice { template, source });
        }
        validate_names(voices.iter().map(|voice| voice.template.name()))?;
        Ok(Self { voices })
    }

    pub fn voices(&self) -> &[SynthVoice] {
        &self.voices
    }

    pub fn matching_voices(
        &self,
        trigger: Trigger,
        key: i64,
        velocity: f64,
    ) -> impl Iterator<Item = &Identifier> {
        self.voices.iter().filter_map(move |voice| {
            let template = voice.template();
            template
                .voice
                .matches(trigger, key, velocity)
                .then_some(template.name())
        })
    }
}

fn amplitude_envelope(
    envelope: Option<Value>,
    limits: PreparationLimits,
) -> Result<(Generator, usize), Error> {
    let envelope = envelope.unwrap_or_else(|| {
        json!({
            "segments": [{"duration": "0 s", "to": 1}],
            "release": [{"duration": "0 s", "to": 0}],
        })
    });
    let count = envelfo::preparation_records(&envelope, limits)?;
    let generator = RootWire::envelope(envelope)?;
    if generator.settings().scope() != Scope::Voice
        || !matches!(generator.body(), Body::Envelope(body) if body.polarity() == Polarity::Unipolar)
    {
        return Err(invalid(
            "amplitude envelope requires voice scope and unipolar levels",
        ));
    }
    Ok((generator, count))
}

fn validate_names<'a>(names: impl Iterator<Item = &'a Identifier>) -> Result<(), Error> {
    let mut seen = BTreeSet::new();
    for name in names {
        if !seen.insert(name) {
            return Err(invalid("duplicate voice name"));
        }
    }
    if seen.is_empty() {
        return Err(invalid("synth instrument requires voices"));
    }
    Ok(())
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

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
