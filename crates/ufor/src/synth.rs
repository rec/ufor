//! Shared synth-family voice metadata and mapped event selection.

use crate::control::Scope;
use crate::envelfo::{self, Body, PreparationLimits};
use crate::error::Error;
use crate::fm::Fm;
use crate::identifier::Identifier;
use crate::modulation::{Target, Unit};
use crate::number::Rational;
use crate::oscillator::Oscillator;
use crate::quantity;
use crate::samples::articulations::Articulations;
use crate::samples::controls::ControlDeclaration;
use crate::samples::eligibility::{Trigger, VoiceMapping};
use crate::samples::playback::Mapping;
use crate::samples::processing::{
    Binding, EventKind, ResolvedTarget, SoundSettings, SoundWire, TargetMinimum, TargetResolution,
};
use crate::samples::routing::ChannelRoute;
use crate::voice_admission::{Choke, VoicePolicy};
use crate::voice_release::Sustain;
use crate::yamaha::Patch;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

pub mod score;
pub mod yamaha;
use yamaha::{Dx7Performance, Tx81zLfoGroup, Tx81zOutput, YamahaWire};

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
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
    #[serde(default)]
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
        value.prepare(false)
    }
}

impl VoiceDefinition {
    fn prepare(self, allow_unrouted: bool) -> Result<VoiceTemplate, Error> {
        let value = self;
        let voice = VoiceMapping {
            name: value.name,
            mapping: value.mapping,
            trigger: value.trigger,
        };
        voice.validate()?;
        if !allow_unrouted && value.channels.is_empty() {
            return Err(invalid("synth voice requires channel routes"));
        }
        validate_channel_routes(&value.channels)?;
        let articulations: BTreeSet<_> = value.articulations.iter().collect();
        if articulations.len() != value.articulations.len() {
            return Err(invalid("duplicate articulation reference"));
        }
        let chokes: BTreeSet<_> = value.chokes.iter().map(Choke::group).collect();
        if chokes.len() != value.chokes.len() {
            return Err(invalid("duplicate choke target"));
        }
        Ok(VoiceTemplate {
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

/// One mapped voice with its source and sound settings.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct SynthVoice {
    #[serde(flatten)]
    template: VoiceTemplate,
    #[serde(flatten)]
    source: VoiceSource,
    #[serde(flatten)]
    settings: SoundSettings,
}

impl SynthVoice {
    pub fn template(&self) -> &VoiceTemplate {
        &self.template
    }

    pub fn source(&self) -> &VoiceSource {
        &self.source
    }

    pub fn settings(&self) -> &SoundSettings {
        &self.settings
    }

    pub fn resolve_target(&self, target: &Target) -> Result<TargetResolution, Error> {
        self.settings
            .resolve_target_with(target, |address| self.source.resolve_target(address))
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(untagged)]
pub enum VoiceSource {
    Oscillator {
        oscillator: Oscillator,
        synchronize_oscillator: bool,
    },
    Noise {
        noise: NoiseKind,
    },
    Fm {
        fm: Fm,
    },
    Yamaha {
        #[serde(flatten)]
        patch: Patch,
        #[serde(skip_serializing_if = "Option::is_none")]
        performance: Option<Dx7Performance>,
    },
}

impl VoiceSource {
    fn resolve_target(&self, target: &Target) -> Option<ResolvedTarget> {
        match self {
            Self::Fm { fm } => fm.resolve_target(target),
            Self::Yamaha { patch, .. } => {
                if target.name().as_str() != "yamaha" {
                    return None;
                }
                let (default_value, minimum) = match target.parameter().as_str() {
                    "pitch_bend" => (0.0, TargetMinimum::Unrestricted),
                    "modulation_wheel" | "breath" | "foot" => (0.0, TargetMinimum::Nonnegative),
                    "portamento" if !matches!(patch, Patch::Dx7(_)) => {
                        (1.0, TargetMinimum::Nonnegative)
                    }
                    "aftertouch" if matches!(patch, Patch::Wt11(_)) => {
                        (0.0, TargetMinimum::Nonnegative)
                    }
                    _ => return None,
                };
                Some(ResolvedTarget {
                    unit: Unit::Ratio,
                    default_value,
                    duration: None,
                    scope: None,
                    minimum,
                })
            }
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NoiseKind {
    White,
}

/// Mapped synth voices in instrument declaration order.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct SynthVoices {
    voices: Vec<SynthVoice>,
}

impl SynthVoices {
    pub(crate) fn decode<'de, D: Deserializer<'de>>(
        decoder: D,
        limits: PreparationLimits,
    ) -> Result<Self, Error> {
        let definition = SynthVoicesDefinition::deserialize(decoder)
            .map_err(|error| invalid(error.to_string()))?;
        Self::prepare(definition.voices, limits, 1, None)
    }

    fn prepare(
        definitions: Vec<SynthVoiceDefinition>,
        limits: PreparationLimits,
        mut records: usize,
        controls: Option<&BTreeMap<Identifier, ControlDeclaration>>,
    ) -> Result<Self, Error> {
        limits.check_records(records)?;
        let mut voices = Vec::new();
        for voice in definitions {
            let SynthVoiceDefinition {
                template,
                oscillator,
                synchronize_oscillator: sync,
                noise,
                fm,
                envelope,
                yamaha,
                mut settings,
            } = voice;
            let yamaha = yamaha.prepare()?;
            let template = template.prepare(matches!(&yamaha, Some((Patch::Tx81z(_), _))))?;
            records += template.records();
            if records > limits.max_records() {
                return Err(Error::Limit("synth voice template records"));
            }
            let remaining = PreparationLimits::new(limits.max_records() - records)?;
            let (source, source_records) = match (oscillator, noise, fm, yamaha) {
                (Some(oscillator), None, None, None) => {
                    let oscillator = serde_json::from_value(oscillator)
                        .map_err(|error| invalid(error.to_string()))?;
                    let synchronize_oscillator = sync
                        .map_or(Ok(false), serde_json::from_value)
                        .map_err(|error| invalid(error.to_string()))?;
                    settings.envelope = Some(amplitude_envelope(envelope));
                    (
                        VoiceSource::Oscillator {
                            oscillator,
                            synchronize_oscillator,
                        },
                        1,
                    )
                }
                (None, Some(noise), None, None) if sync.is_none() => {
                    let noise = serde_json::from_value(noise)
                        .map_err(|error| invalid(error.to_string()))?;
                    if template.mapping().pitch_tracking() || template.frequency_offset_hz() != 0.0
                    {
                        return Err(invalid("noise does not support pitch tracking or offsets"));
                    }
                    settings.envelope = Some(amplitude_envelope(envelope));
                    (VoiceSource::Noise { noise }, 1)
                }
                (None, None, Some(fm), None) if sync.is_none() => {
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
                (None, None, None, Some((patch, performance))) if sync.is_none() => {
                    if envelope.is_some_and(|envelope| !envelope.is_null()) {
                        return Err(invalid("Yamaha voices use patch operator envelopes"));
                    }
                    // Count the patch plus each additional buffer or DX7 controller declaration.
                    let count = match &patch {
                        Patch::Dx7(_) => 5,
                        Patch::Tx81z(_) => 2,
                        Patch::Wt11(_) => 3,
                    };
                    (VoiceSource::Yamaha { patch, performance }, count)
                }
                _ => {
                    return Err(invalid(
                        "synth voice requires exactly one oscillator, noise, FM or Yamaha source",
                    ));
                }
            };
            records += source_records;
            limits.check_records(records)?;
            // The voice template already accounts for the flat settings root.
            let remaining = PreparationLimits::new(limits.max_records() - records + 1)?;
            let settings =
                settings.prepare(remaining, controls, |target| source.resolve_target(target))?;
            if matches!(source, VoiceSource::Yamaha { .. })
                && settings.modulation().parameters().iter().any(|parameter| {
                    let target = parameter.target();
                    let minimum = if target.parameter().as_str() == "pitch_bend" {
                        -1.0
                    } else {
                        0.0
                    };
                    target.name().as_str() == "yamaha"
                        && (parameter.minimum() < minimum || parameter.maximum() > 1.0)
                })
            {
                return Err(invalid(
                    "Yamaha controller domain exceeds its normalized range",
                ));
            }
            if matches!(source, VoiceSource::Noise { .. })
                && (settings.processing().tuning_cents() != 0.0
                    || settings.modulation().parameters().iter().any(|parameter| {
                        let target = parameter.target();
                        target.name().as_str() == "processing"
                            && target.parameter().as_str() == "tuning_cents"
                    }))
            {
                return Err(invalid("noise does not support tuning"));
            }
            records += settings.records() - 1;
            voices.push(SynthVoice {
                template,
                source,
                settings,
            });
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

/// A synth instrument with authored oscillator, FM or noise voices.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct SynthInstrument {
    controls: BTreeMap<Identifier, ControlDeclaration>,
    #[serde(skip_serializing_if = "Option::is_none")]
    voice_policy: Option<VoicePolicy>,
    #[serde(skip_serializing_if = "Option::is_none")]
    sustain: Option<Sustain>,
    #[serde(skip_serializing_if = "Option::is_none")]
    articulations: Option<Articulations>,
    #[serde(flatten)]
    voices: SynthVoices,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    tx81z_outputs: Vec<Tx81zOutput>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    tx81z_lfos: Vec<Tx81zLfoGroup>,
    #[serde(skip)]
    sustain_pressed: bool,
}

impl SynthInstrument {
    pub(crate) fn decode<'de, D: Deserializer<'de>>(
        decoder: D,
        limits: PreparationLimits,
    ) -> Result<Self, Error> {
        let definition = InstrumentDefinition::deserialize(decoder)
            .map_err(|error| invalid(error.to_string()))?;
        Self::prepare(definition, limits)
    }

    fn prepare(definition: InstrumentDefinition, limits: PreparationLimits) -> Result<Self, Error> {
        if definition.voices.is_empty() {
            return Err(invalid("synth instrument requires at least one voice"));
        }
        let mut records = 1
            + definition.controls.len()
            + usize::from(definition.voice_policy.is_some())
            + usize::from(definition.sustain.is_some());
        records += definition
            .tx81z_outputs
            .iter()
            .map(Tx81zOutput::records)
            .sum::<usize>();
        records += definition
            .tx81z_lfos
            .iter()
            .map(Tx81zLfoGroup::records)
            .sum::<usize>();
        if let Some(articulations) = &definition.articulations {
            records += 1
                + articulations.ids().len()
                + articulations.keys().len()
                + articulations.controls().len();
            articulations.validate_controls(&definition.controls)?;
        }
        let sustain_pressed = if let Some(sustain) = &definition.sustain {
            let control = definition.controls.get(sustain.control()).ok_or_else(|| {
                invalid(format!(
                    "Unknown sustain control: {}",
                    sustain.control().as_str()
                ))
            })?;
            sustain.initially_pressed(control)?
        } else {
            false
        };
        let voices = SynthVoices::prepare(
            definition.voices,
            limits,
            records,
            Some(&definition.controls),
        )?;
        yamaha::validate_routing(&voices, &definition.tx81z_outputs, &definition.tx81z_lfos)?;
        let choke_groups: BTreeSet<_> = voices
            .voices()
            .iter()
            .filter_map(|voice| voice.template().choke_group())
            .collect();
        let articulations: BTreeSet<_> = definition
            .articulations
            .iter()
            .flat_map(Articulations::ids)
            .collect();
        for voice in voices.voices() {
            validate_instrument_voice(
                voice,
                definition.sustain.is_some(),
                &articulations,
                &choke_groups,
            )?;
        }
        Ok(Self {
            controls: definition.controls,
            voice_policy: definition.voice_policy,
            sustain: definition.sustain,
            articulations: definition.articulations,
            voices,
            tx81z_outputs: definition.tx81z_outputs,
            tx81z_lfos: definition.tx81z_lfos,
            sustain_pressed,
        })
    }

    pub fn controls(&self) -> &BTreeMap<Identifier, ControlDeclaration> {
        &self.controls
    }

    pub fn voice_policy(&self) -> Option<&VoicePolicy> {
        self.voice_policy.as_ref()
    }

    pub fn sustain(&self) -> Option<&Sustain> {
        self.sustain.as_ref()
    }

    pub fn articulations(&self) -> Option<&Articulations> {
        self.articulations.as_ref()
    }

    pub fn voices(&self) -> &SynthVoices {
        &self.voices
    }

    pub fn tx81z_outputs(&self) -> &[Tx81zOutput] {
        &self.tx81z_outputs
    }

    pub fn tx81z_lfos(&self) -> &[Tx81zLfoGroup] {
        &self.tx81z_lfos
    }

    pub fn sustain_pressed(&self) -> bool {
        self.sustain_pressed
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct InstrumentDefinition {
    #[serde(default)]
    controls: BTreeMap<Identifier, ControlDeclaration>,
    voice_policy: Option<VoicePolicy>,
    sustain: Option<Sustain>,
    articulations: Option<Articulations>,
    voices: Vec<SynthVoiceDefinition>,
    #[serde(default)]
    tx81z_outputs: Vec<Tx81zOutput>,
    #[serde(default)]
    tx81z_lfos: Vec<Tx81zLfoGroup>,
}

fn validate_instrument_voice(
    voice: &SynthVoice,
    has_sustain: bool,
    articulations: &BTreeSet<&Identifier>,
    choke_groups: &BTreeSet<&Identifier>,
) -> Result<(), Error> {
    let template = voice.template();
    let settings = voice.settings();
    let modulation = settings.modulation();
    let sources: BTreeMap<_, _> = modulation.sources().iter().map(|s| (s.name(), s)).collect();
    let keys = template.mapping().note_range();
    for binding in settings.bindings() {
        let binding = match binding {
            Binding::Event(binding) if binding.kind() == EventKind::Key => binding,
            _ => continue,
        };
        let source = sources[binding.name()];
        // Key source bounds are already validated as integral binary64 values.
        // Widen the integer keys to avoid rounding them before comparison.
        if source.minimum() as i128 > i128::from(*keys.start())
            || (source.maximum() as i128) < i128::from(*keys.end())
        {
            return Err(invalid(
                "NoteKey source domain must cover the voice mapping",
            ));
        }
    }
    if modulation
        .parameters()
        .iter()
        .any(|p| p.scope() != Scope::Voice)
    {
        return Err(invalid("Synth voice parameters must have voice scope"));
    }
    if settings
        .envelfos()
        .iter()
        .any(|(_, g)| matches!(g.body(), Body::Envelope(_)) && g.settings().scope() != Scope::Voice)
    {
        return Err(invalid("Synth voice envelopes must have voice scope"));
    }
    if matches!(
        template.trigger(),
        Trigger::SustainPress | Trigger::SustainRelease
    ) && !has_sustain
    {
        return Err(invalid("Sustain voices require a sustain control"));
    }
    for name in template.articulations() {
        if !articulations.contains(name) {
            return Err(invalid(format!(
                "Synth voice {}: unknown articulation {}",
                template.name().as_str(),
                name.as_str()
            )));
        }
    }
    for choke in template.chokes() {
        if !choke_groups.contains(choke.group()) {
            return Err(invalid(format!(
                "Synth voice {}: unknown choke group {}",
                template.name().as_str(),
                choke.group().as_str()
            )));
        }
    }
    Ok(())
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SynthVoicesDefinition {
    voices: Vec<SynthVoiceDefinition>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SynthVoiceDefinition {
    #[serde(flatten)]
    template: VoiceDefinition,
    #[serde(flatten)]
    settings: SoundWire,
    #[serde(flatten)]
    yamaha: YamahaWire,
    #[serde(default, deserialize_with = "present_value")]
    oscillator: Option<Value>,
    #[serde(default, deserialize_with = "present_value")]
    synchronize_oscillator: Option<Value>,
    #[serde(default, deserialize_with = "present_value")]
    noise: Option<Value>,
    #[serde(default, deserialize_with = "present_value")]
    fm: Option<Value>,
    #[serde(default, deserialize_with = "present_value")]
    envelope: Option<Value>,
}

fn present_value<'de, D: Deserializer<'de>>(decoder: D) -> Result<Option<Value>, D::Error> {
    Value::deserialize(decoder).map(Some)
}

fn validate_channel_routes(channels: &[ChannelRoute]) -> Result<(), Error> {
    let mut routes = BTreeSet::new();
    for route in channels {
        if route.input.is_empty() || route.output.is_empty() || !route.gain.is_finite() {
            return Err(invalid("invalid synth voice channel route"));
        }
        if !routes.insert((&route.input, &route.output)) {
            return Err(invalid("duplicate channel route"));
        }
    }
    Ok(())
}

fn amplitude_envelope(envelope: Option<Value>) -> Value {
    envelope.unwrap_or_else(|| {
        json!({
            "segments": [{"duration": "0 s", "to": 1}],
            "release": [{"duration": "0 s", "to": 0}],
        })
    })
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
