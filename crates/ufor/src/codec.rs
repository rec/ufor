//! UTF-8 JSON/TOML interchange for the implemented bodies and score kinds.

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::automation::Automation;
use crate::automation::placement::ControlClip;
use crate::control::tempo::TempoMap;
use crate::effects::Processor;
use crate::effects::actions::{Action, ActionBatch};
use crate::effects::topology::Topology;
use crate::envelfo::{Generator, PreparationLimits};
use crate::error::Error;
use crate::events::captured::JsonCapture;
use crate::events::{EventKind, PerformanceEvent, PerformancePayload, StoredEvent};
use crate::fm::Fm;
use crate::modulation::{Modulation, Target};
use crate::oscillator::Oscillator;
use crate::performance_binding::MidiBindings;
use crate::playback::SequenceSelection;
use crate::samples::articulations::Articulations;
use crate::samples::eligibility::{Context as EligibilityContext, Eligibility, VoiceEligibility};
use crate::samples::playback::{Mapping, Playback, Slice, SlotPlayback};
use crate::samples::processing::{ResolvedTarget, SoundSettings};
use crate::samples::selection::{Sequence, TakeSelector};
use crate::samples::variation::Variation;
use crate::samples::{assets::Inventory, crossfade::Crossfade};
use crate::scale::Scale;
use crate::score::Score;
use crate::sequence::EventSequence;
use crate::synth::{SynthInstrument, SynthVoices, VoiceTemplates};
use crate::time::Timebase;
use crate::tuning::Tuning;
use crate::voice_admission::{Admission, Choke, VoicePolicy, VoicePool};
use crate::voice_release::{ReleaseRequest, Sustain};

pub const MAX_SCORE_CHARACTERS: usize = 16 * 1024 * 1024;
pub const MAX_DOCUMENT_VALUES: usize = 100_000;
pub const MAX_DOCUMENT_DEPTH: usize = 64;

#[derive(Clone, Copy, Debug)]
pub enum Format {
    Json,
    Toml,
}

pub fn parse_tuning(text: &str, format: Format) -> Result<Tuning, Error> {
    serde_json::from_value(parse_value(text, format)?).map_err(|e| Error::Invalid(e.to_string()))
}

pub fn parse_scale(text: &str, format: Format) -> Result<Scale, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn scale_text(value: &Scale, format: Format) -> Result<String, Error> {
    write(value, format)
}

pub fn parse_performance_event(text: &str, format: Format) -> Result<PerformanceEvent, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn performance_event_text(value: &PerformanceEvent, format: Format) -> Result<String, Error> {
    write(value, format)
}

pub fn parse_performance_payload(text: &str, format: Format) -> Result<PerformancePayload, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn parse_stored_event(text: &str, format: Format) -> Result<StoredEvent, Error> {
    let value = parse_value(text, format)?;
    match format {
        Format::Json => {
            let event: StoredEvent =
                serde_json::from_value(value).map_err(|error| Error::Invalid(error.to_string()))?;
            if event.payload.kind() == EventKind::Osc {
                let capture: JsonCapture<'_> = serde_json::from_str(text)
                    .map_err(|error| Error::Invalid(error.to_string()))?;
                capture.check_integers()?;
            }
            Ok(event)
        }
        Format::Toml => toml::from_str(text).map_err(|error| Error::Invalid(error.to_string())),
    }
}

pub fn stored_event_text(value: &StoredEvent, format: Format) -> Result<String, Error> {
    if matches!(format, Format::Toml) {
        value.payload.check_toml()?;
    }
    write(value, format)
}

pub fn parse_event_sequence(
    text: &str,
    format: Format,
    limits: PreparationLimits,
) -> Result<EventSequence, Error> {
    let value = parse_value(text, format)?;
    let sequence: EventSequence = match format {
        Format::Json => {
            serde_json::from_value(value).map_err(|error| Error::Invalid(error.to_string()))?
        }
        Format::Toml => toml::from_str(text).map_err(|error| Error::Invalid(error.to_string()))?,
    };
    if 1 + sequence.events().len() > limits.max_records() {
        return Err(Error::Limit("event sequence records"));
    }
    if matches!(format, Format::Json) && sequence_has_osc(&sequence) {
        let sequence: JsonSequence<'_> =
            serde_json::from_str(text).map_err(|error| Error::Invalid(error.to_string()))?;
        sequence.check_integers()?;
    }
    Ok(sequence)
}

pub fn event_sequence_text(value: &EventSequence, format: Format) -> Result<String, Error> {
    if matches!(format, Format::Toml) {
        value.check_toml()?;
    }
    write(value, format)
}

pub fn parse_sequence_selection(text: &str, format: Format) -> Result<SequenceSelection, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn sequence_selection_text(value: &SequenceSelection, format: Format) -> Result<String, Error> {
    write(value, format)
}

pub fn parse_oscillator(text: &str, format: Format) -> Result<Oscillator, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn oscillator_text(value: &Oscillator, format: Format) -> Result<String, Error> {
    write(value, format)
}

pub fn parse_tempo_map(
    text: &str,
    format: Format,
    limits: PreparationLimits,
) -> Result<TempoMap, Error> {
    TempoMap::decode(parse_value(text, format)?, limits)
}

pub fn parse_automation(
    text: &str,
    format: Format,
    limits: PreparationLimits,
) -> Result<Automation, Error> {
    let automation: Automation = serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))?;
    automation.check_records(limits, 0)?;
    Ok(automation)
}

pub fn automation_text(value: &Automation, format: Format) -> Result<String, Error> {
    write(value, format)
}

pub fn parse_control_clip(text: &str, format: Format) -> Result<ControlClip, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn parse_timebase(text: &str, format: Format) -> Result<Timebase, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn parse_midi_bindings(
    text: &str,
    format: Format,
    limits: PreparationLimits,
) -> Result<MidiBindings, Error> {
    MidiBindings::decode(parse_value(text, format)?, limits)
}

pub fn parse_sample_slice(text: &str, format: Format) -> Result<Slice, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn parse_articulations(
    text: &str,
    format: Format,
    limits: PreparationLimits,
) -> Result<Articulations, Error> {
    let value: Articulations = serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))?;
    value.check_records(limits)?;
    Ok(value)
}

pub fn articulations_text(value: &Articulations, format: Format) -> Result<String, Error> {
    write(value, format)
}

pub fn parse_sample_inventory(
    text: &str,
    format: Format,
    limits: PreparationLimits,
) -> Result<Inventory, Error> {
    Inventory::decode(parse_value(text, format)?, limits)
}

pub fn parse_sample_mapping(text: &str, format: Format) -> Result<Mapping, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn parse_sample_crossfade(text: &str, format: Format) -> Result<Crossfade, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn parse_sample_eligibility(
    text: &str,
    format: Format,
    maximum: usize,
) -> Result<Eligibility, Error> {
    Eligibility::decode(parse_value(text, format)?, maximum)
}

pub fn parse_voice_eligibility(
    text: &str,
    format: Format,
    maximum: usize,
) -> Result<VoiceEligibility, Error> {
    VoiceEligibility::decode(parse_value(text, format)?, maximum)
}

pub fn parse_synth_voice_templates(
    text: &str,
    format: Format,
    limits: PreparationLimits,
) -> Result<VoiceTemplates, Error> {
    VoiceTemplates::decode(parse_value(text, format)?, limits)
}

pub fn parse_synth_voices(
    text: &str,
    format: Format,
    limits: PreparationLimits,
) -> Result<SynthVoices, Error> {
    parse_value(text, format)?;
    match format {
        Format::Json => {
            let mut decoder = serde_json::Deserializer::from_str(text);
            SynthVoices::decode(&mut decoder, limits)
        }
        Format::Toml => SynthVoices::decode(
            toml::de::Deserializer::parse(text).map_err(|e| Error::Invalid(e.to_string()))?,
            limits,
        ),
    }
}

pub fn parse_synth_instrument(
    text: &str,
    format: Format,
    limits: PreparationLimits,
) -> Result<SynthInstrument, Error> {
    parse_value(text, format)?;
    match format {
        Format::Json => {
            SynthInstrument::decode(&mut serde_json::Deserializer::from_str(text), limits)
        }
        Format::Toml => SynthInstrument::decode(
            toml::de::Deserializer::parse(text)
                .map_err(|error| Error::Invalid(error.to_string()))?,
            limits,
        ),
    }
}

pub fn parse_sample_eligibility_context(
    text: &str,
    format: Format,
) -> Result<EligibilityContext, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn parse_sample_selection_sequence(text: &str, format: Format) -> Result<Sequence, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn parse_sample_take_selector(
    text: &str,
    format: Format,
    seed: u64,
    limits: PreparationLimits,
) -> Result<TakeSelector, Error> {
    TakeSelector::decode(parse_value(text, format)?, seed, limits)
}

pub fn parse_sample_variation(text: &str, format: Format) -> Result<Variation, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn parse_voice_admission(text: &str, format: Format) -> Result<Admission, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn parse_choke(text: &str, format: Format) -> Result<Choke, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn parse_voice_policy(text: &str, format: Format) -> Result<VoicePolicy, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn parse_voice_pool(text: &str, format: Format) -> Result<VoicePool, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn parse_voice_release(text: &str, format: Format) -> Result<ReleaseRequest, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn parse_sustain(text: &str, format: Format) -> Result<Sustain, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn sustain_text(value: &Sustain, format: Format) -> Result<String, Error> {
    write(value, format)
}

pub fn parse_sample_playback(text: &str, format: Format) -> Result<Playback, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn parse_slot_playback(text: &str, format: Format) -> Result<SlotPlayback, Error> {
    let value = parse_value(text, format)?;
    let normalized;
    let text = match format {
        Format::Json => text,
        Format::Toml => {
            normalized = value.to_string();
            &normalized
        }
    };
    serde_json::from_str(text).map_err(|error| Error::Invalid(error.to_string()))
}

pub fn tempo_map_text(value: &TempoMap, format: Format) -> Result<String, Error> {
    write(value, format)
}

pub fn tuning_text(value: &Tuning, format: Format) -> Result<String, Error> {
    write(value, format)
}

pub fn parse_modulation(text: &str, format: Format) -> Result<Modulation, Error> {
    serde_json::from_value(parse_value(text, format)?).map_err(|e| Error::Invalid(e.to_string()))
}

pub fn modulation_text(value: &Modulation, format: Format) -> Result<String, Error> {
    write(value, format)
}

pub fn parse_effect_processor(
    text: &str,
    format: Format,
    limits: PreparationLimits,
) -> Result<Processor, Error> {
    let value = parse_value(text, format)?;
    crate::envelfo::preparation_records(&value, limits)?;
    serde_json::from_value(value).map_err(|error| Error::Invalid(error.to_string()))
}

pub fn parse_effect_topology(
    text: &str,
    format: Format,
    limits: PreparationLimits,
) -> Result<Topology, Error> {
    Topology::decode(parse_value(text, format)?, limits)
}

pub fn parse_effect_action(text: &str, format: Format) -> Result<Action, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn parse_effect_action_batch(text: &str, format: Format) -> Result<ActionBatch, Error> {
    serde_json::from_value(parse_value(text, format)?)
        .map_err(|error| Error::Invalid(error.to_string()))
}

pub fn parse_fm(text: &str, format: Format, limits: PreparationLimits) -> Result<Fm, Error> {
    let value = parse_value(text, format)?;
    crate::envelfo::preparation_records(&value, limits)?;
    Fm::decode(value, limits).map_err(|error| Error::Invalid(error.to_string()))
}

pub fn fm_text(value: &Fm, format: Format) -> Result<String, Error> {
    write(value, format)
}

/// Decode a base SoundSettings body, before supplying external context.
pub fn parse_sound_settings(
    text: &str,
    format: Format,
    limits: PreparationLimits,
) -> Result<SoundSettings, Error> {
    parse_sound_settings_with_targets(text, format, limits, |_| None)
}

pub fn parse_sound_settings_with_targets(
    text: &str,
    format: Format,
    limits: PreparationLimits,
    engine: impl Fn(&Target) -> Option<ResolvedTarget>,
) -> Result<SoundSettings, Error> {
    let data = parse_value(text, format)?;
    crate::envelfo::preparation_records(&data, limits)?;
    match format {
        Format::Json => {
            let mut decoder = serde_json::Deserializer::from_str(text);
            let value = SoundSettings::decode_with_targets(&mut decoder, limits, engine)
                .map_err(|e| Error::Invalid(e.to_string()))?;
            decoder.end().map_err(|e| Error::Invalid(e.to_string()))?;
            Ok(value)
        }
        Format::Toml => SoundSettings::decode_with_targets(
            toml::de::Deserializer::parse(text).map_err(|e| Error::Invalid(e.to_string()))?,
            limits,
            engine,
        )
        .map_err(|e| Error::Invalid(e.to_string())),
    }
}

pub fn sound_settings_text(value: &SoundSettings, format: Format) -> Result<String, Error> {
    write(value, format)
}

/// Validate document budgets before typed decoding of the original map order.
pub fn parse_generator(
    text: &str,
    format: Format,
    limits: PreparationLimits,
) -> Result<Generator, Error> {
    let document = parse_value(text, format)?;
    crate::envelfo::preparation_records(&document, limits)?;
    match format {
        Format::Json => {
            let mut decoder = serde_json::Deserializer::from_str(text);
            let value = Generator::decode(&mut decoder, limits)
                .map_err(|e| Error::Invalid(e.to_string()))?;
            decoder.end().map_err(|e| Error::Invalid(e.to_string()))?;
            Ok(value)
        }
        Format::Toml => Generator::decode(
            toml::de::Deserializer::parse(text).map_err(|e| Error::Invalid(e.to_string()))?,
            limits,
        )
        .map_err(|e| Error::Invalid(e.to_string())),
    }
}

pub fn generator_text(value: &Generator, format: Format) -> Result<String, Error> {
    write(value, format)
}

pub fn parse_score(text: &str, format: Format, limits: PreparationLimits) -> Result<Score, Error> {
    parse_value(text, format)?;
    match format {
        Format::Json => {
            let mut decoder = serde_json::Deserializer::from_str(text);
            let value =
                Score::decode(&mut decoder, limits).map_err(|e| Error::Invalid(e.to_string()))?;
            decoder.end().map_err(|e| Error::Invalid(e.to_string()))?;
            if matches!(&value, Score::Sequence(sequence) if sequence_has_osc(sequence.body())) {
                #[derive(Deserialize)]
                struct JsonSequenceScore<'a> {
                    #[serde(borrow)]
                    body: JsonSequence<'a>,
                }
                let score: JsonSequenceScore<'_> = serde_json::from_str(text)
                    .map_err(|error| Error::Invalid(error.to_string()))?;
                score.body.check_integers()?;
            }
            Ok(value)
        }
        Format::Toml => Score::decode(
            toml::de::Deserializer::parse(text).map_err(|e| Error::Invalid(e.to_string()))?,
            limits,
        )
        .map_err(|e| Error::Invalid(e.to_string())),
    }
}

pub fn score_text(value: &Score, format: Format) -> Result<String, Error> {
    if let (Format::Toml, Score::Sequence(sequence)) = (format, value) {
        sequence.body().check_toml()?;
    }
    write(value, format)
}

/// Decode a generic value with the shared character, value-count and depth limits.
///
/// This checks document budgets, not domain validity. Object declaration order is
/// not retained in `Value`; use `parse_generator` or `parse_score` on the original
/// text for order-sensitive definitions.
pub fn parse_value(text: &str, format: Format) -> Result<Value, Error> {
    if text.chars().take(MAX_SCORE_CHARACTERS + 1).count() > MAX_SCORE_CHARACTERS {
        return Err(Error::Limit("score characters"));
    }
    let value = match format {
        Format::Json => serde_json::from_str(text).map_err(|e| Error::Invalid(e.to_string()))?,
        Format::Toml => {
            let value: toml::Value =
                toml::from_str(text).map_err(|e| Error::Invalid(e.to_string()))?;
            serde_json::to_value(value).map_err(|e| Error::Invalid(e.to_string()))?
        }
    };
    let mut pending = vec![(&value, 0)];
    let mut count = 0;
    while let Some((item, depth)) = pending.pop() {
        count += 1;
        if count > MAX_DOCUMENT_VALUES || depth > MAX_DOCUMENT_DEPTH {
            return Err(Error::Limit("document values or depth"));
        }
        match item {
            Value::Array(values) => pending.extend(values.iter().map(|v| (v, depth + 1))),
            Value::Object(values) => pending.extend(values.values().map(|v| (v, depth + 1))),
            _ => (),
        }
    }
    Ok(value)
}

fn write<T: Serialize>(value: &T, format: Format) -> Result<String, Error> {
    match format {
        Format::Json => {
            serde_json::to_string_pretty(value).map_err(|e| Error::Invalid(e.to_string()))
        }
        Format::Toml => toml::to_string_pretty(value).map_err(|e| Error::Invalid(e.to_string())),
    }
}

#[derive(Deserialize)]
struct JsonSequence<'a> {
    #[serde(default, borrow)]
    events: Vec<JsonCapture<'a>>,
}

impl JsonSequence<'_> {
    fn check_integers(&self) -> Result<(), Error> {
        self.events.iter().try_for_each(JsonCapture::check_integers)
    }
}

fn sequence_has_osc(sequence: &EventSequence) -> bool {
    sequence
        .events()
        .iter()
        .any(|e| e.payload.kind() == EventKind::Osc)
}
