//! Prepared MIDI 1 channel assignments and control mappings.

use crate::envelfo::{PreparationLimits, ScoreReference};
use crate::musical::header;
use crate::{error::Error, identifier::Identifier};
use crate::{samples::controls::ControlDeclaration, tuning::Tuning};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet, VecDeque};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RepeatedKeyRelease {
    Oldest,
    Newest,
}

/// An authored MIDI performance binding with unresolved resource references.
#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(try_from = "ScoreDefinition")]
pub struct PerformanceBindingScore {
    format: String,
    version: i64,
    kind: String,
    name: String,
    title: String,
    tags: Vec<String>,
    body: PerformanceInputBinding,
    #[serde(skip)]
    channels: [Option<usize>; 16],
}

impl PerformanceBindingScore {
    pub fn name(&self) -> &str {
        &self.name
    }

    pub fn title(&self) -> &str {
        &self.title
    }

    pub fn tags(&self) -> &[String] {
        &self.tags
    }

    pub fn instrument(&self) -> &ScoreReference {
        &self.body.instrument
    }

    pub fn tuning_references(&self) -> impl Iterator<Item = &ScoreReference> {
        self.body
            .midi
            .iter()
            .filter_map(|input| input.tuning.as_ref())
    }

    pub(crate) fn check_records(&self, limits: PreparationLimits) -> Result<(), Error> {
        if self.records() > limits.max_records() {
            return Err(Error::Limit("MIDI binding records"));
        }
        Ok(())
    }

    fn records(&self) -> usize {
        // The score, body and instrument reference precede the MIDI records.
        3 + self
            .body
            .midi
            .iter()
            .map(|input| {
                1 + input.channels.len()
                    + input.controllers.len()
                    + usize::from(input.pitch_bend.is_some())
                    + usize::from(input.tuning.is_some())
            })
            .sum::<usize>()
    }
}

impl TryFrom<ScoreDefinition> for PerformanceBindingScore {
    type Error = Error;

    fn try_from(value: ScoreDefinition) -> Result<Self, Error> {
        if value.format != "recs" || value.version != 4 || value.kind != "performance_binding" {
            return Err(invalid(
                "expected a recs version 4 performance binding score",
            ));
        }
        if value.body.midi.is_empty() {
            return Err(invalid("MIDI bindings require at least one input"));
        }
        let tags = header(&value.name, &value.title, value.tags)?;
        let mut channels = [None; 16];
        for (index, input) in value.body.midi.iter().enumerate() {
            if input.channels.is_empty() {
                return Err(invalid("MIDI input requires at least one channel"));
            }
            for &channel in &input.channels {
                let slot = channel_index(channel)
                    .ok_or_else(|| invalid("MIDI channel must be in [1, 16]"))?;
                if channels[slot].replace(index).is_some() {
                    return Err(invalid("Duplicate MIDI channel"));
                }
            }
            let mut numbers = BTreeSet::new();
            for controller in &input.controllers {
                if controller.number > 127 || !numbers.insert(controller.number) {
                    return Err(invalid("Invalid or duplicate MIDI controller number"));
                }
                if !bipolar_range(controller.minimum, controller.maximum) {
                    return Err(invalid(
                        "MIDI controller output range must increase within [-1, 1]",
                    ));
                }
            }
            if let Some(bend) = &input.pitch_bend {
                if !(bipolar_range(bend.minimum, bend.maximum)
                    && bend.minimum < bend.center
                    && bend.center < bend.maximum)
                {
                    return Err(invalid(
                        "MIDI pitch-bend minimum < center < maximum required within [-1, 1]",
                    ));
                }
            }
        }
        Ok(Self {
            format: value.format,
            version: value.version,
            kind: value.kind,
            name: value.name,
            title: value.title,
            tags,
            body: value.body,
            channels,
        })
    }
}

/// Resolved facts for a note onset, before host coordinates are attached.
#[derive(Debug, PartialEq)]
pub struct NoteStart {
    pub trigger_id: String,
    pub velocity: f64,
    pub pitch_hz: f64,
}

/// Held-note state for one MIDI source, independent of host timing.
pub struct HeldNotes {
    source: Identifier,
    limit: usize,
    held: BTreeMap<(u8, u8), VecDeque<u64>>,
    count: usize,
    next_id: u64,
    stopped: bool,
}

impl HeldNotes {
    pub fn new(source: Identifier, limit: usize) -> Result<Self, Error> {
        if limit == 0 {
            return Err(invalid("max_held_notes must be a positive integer"));
        }
        Ok(Self {
            source,
            limit,
            held: BTreeMap::new(),
            count: 0,
            next_id: 0,
            stopped: false,
        })
    }

    pub fn source(&self) -> &Identifier {
        &self.source
    }

    pub fn stopped(&self) -> bool {
        self.stopped
    }

    pub fn note_on(
        &mut self,
        channel: u8,
        key: u8,
        velocity: u8,
        tuning: Option<&Tuning>,
    ) -> Result<NoteStart, Error> {
        self.require_running()?;
        if channel_index(channel).is_none() || key > 127 || !(1..=127).contains(&velocity) {
            return self.fail("Invalid MIDI note-on");
        }
        if self.count >= self.limit {
            return self.fail("MIDI held-note limit exceeded");
        }
        let pitch_hz = match tuning {
            Some(tuning) => match tuning.evaluate(i64::from(key)) {
                Ok(pitch) => pitch.as_f64(),
                Err(error) => return self.fail(format!("Cannot convert MIDI note {key}: {error}")),
            },
            None => 440.0 * 2.0_f64.powf((f64::from(key) - 69.0) / 12.0),
        };
        let id = self.next_id;
        let Some(next) = id.checked_add(1) else {
            return self.fail("MIDI trigger ID limit exceeded");
        };
        self.held.entry((channel, key)).or_default().push_back(id);
        self.count += 1;
        self.next_id = next;
        Ok(NoteStart {
            trigger_id: self.trigger_id(id),
            velocity: f64::from(velocity) / 127.0,
            pitch_hz,
        })
    }

    pub fn note_off(
        &mut self,
        channel: u8,
        key: u8,
        policy: RepeatedKeyRelease,
    ) -> Result<String, Error> {
        self.require_running()?;
        let address = (channel, key);
        let Some(queue) = self.held.get_mut(&address) else {
            return self.fail("Unmatched MIDI note-off");
        };
        let id = match policy {
            RepeatedKeyRelease::Oldest => queue.pop_front(),
            RepeatedKeyRelease::Newest => queue.pop_back(),
        }
        .expect("held queues are nonempty");
        if queue.is_empty() {
            self.held.remove(&address);
        }
        self.count -= 1;
        Ok(self.trigger_id(id))
    }

    pub fn report_loss(&mut self) {
        self.held.clear();
        self.count = 0;
        self.stopped = true;
    }

    /// Begin a fresh observation sequence without reusing trigger IDs.
    pub fn restart(&mut self) {
        self.report_loss();
        self.stopped = false;
    }

    pub fn finish(&mut self) -> Result<(), Error> {
        self.require_running()?;
        if !self.held.is_empty() {
            return self.fail("MIDI source ends with unreleased notes");
        }
        self.stopped = true;
        Ok(())
    }

    fn require_running(&self) -> Result<(), Error> {
        if self.stopped {
            return Err(invalid("MIDI converter requires explicit restart"));
        }
        Ok(())
    }

    fn trigger_id(&self, id: u64) -> String {
        format!("{}-note-{id}", self.source.as_str())
    }

    fn fail<T>(&mut self, message: impl Into<String>) -> Result<T, Error> {
        self.report_loss();
        Err(invalid(message))
    }
}

/// Bound destination for one decoded control value.
#[derive(Debug, PartialEq)]
pub struct ControlValue<'a> {
    pub part: &'a Identifier,
    pub control: &'a Identifier,
    pub value: f64,
}

/// Prepared MIDI channel layout and control mappings.
pub struct MidiBindings {
    inputs: Vec<Input>,
    channels: [Option<usize>; 16],
    tuning_indices: [Option<usize>; 16],
    tunings: Vec<Tuning>,
}

impl MidiBindings {
    pub(crate) fn decode(
        score: PerformanceBindingScore,
        value: serde_json::Value,
        limits: PreparationLimits,
    ) -> Result<Self, Error> {
        let Definitions {
            controls,
            tunings: mut tuning_definitions,
        } = serde_json::from_value(value).map_err(|error| invalid(error.to_string()))?;
        let mut records = score.records() + controls.as_ref().map_or(0, BTreeMap::len);
        if records > limits.max_records() {
            return Err(Error::Limit("MIDI binding records"));
        }
        let mut tuning_indices = [None; 16];
        let mut indices = BTreeMap::new();
        let mut tunings = Vec::new();
        for input in &score.body.midi {
            if let Some(controls) = &controls {
                for controller in &input.controllers {
                    validate_control(
                        controls,
                        &controller.control,
                        controller.minimum,
                        controller.maximum,
                    )?;
                }
                if let Some(bend) = &input.pitch_bend {
                    validate_control(controls, &bend.control, bend.minimum, bend.maximum)?;
                }
            }
            if let Some(reference) = &input.tuning {
                let key = reference.key();
                let index = if let Some(&index) = indices.get(&key) {
                    index
                } else {
                    records += 1;
                    if records > limits.max_records() {
                        return Err(Error::Limit("MIDI binding records"));
                    }
                    let definition = tuning_definitions
                        .remove(&key)
                        .ok_or_else(|| invalid(format!("Unresolved tuning: {key}")))?;
                    let tuning = serde_json::from_value(definition).map_err(|error| {
                        invalid(format!("Cannot prepare tuning {key}: {error}"))
                    })?;
                    let index = tunings.len();
                    tunings.push(tuning);
                    indices.insert(key, index);
                    index
                };
                for &channel in &input.channels {
                    tuning_indices[usize::from(channel - 1)] = Some(index);
                }
            }
        }
        Ok(Self {
            inputs: score.body.midi,
            channels: score.channels,
            tuning_indices,
            tunings,
        })
    }

    pub fn parts(&self) -> impl Iterator<Item = &Identifier> {
        let mut seen = BTreeSet::new();
        self.inputs
            .iter()
            .map(|input| &input.part)
            .filter(move |part| seen.insert(*part))
    }

    pub fn note_route(&self, channel: u8) -> Option<(&Identifier, RepeatedKeyRelease)> {
        let input = self.input(channel)?;
        Some((&input.part, input.repeated_key_release))
    }

    pub fn tuning(&self, channel: u8) -> Option<&Tuning> {
        self.tunings
            .get(self.tuning_indices[channel_index(channel)?]?)
    }

    pub fn control_change(
        &self,
        channel: u8,
        controller: u8,
        value: u8,
    ) -> Result<Option<ControlValue<'_>>, Error> {
        if controller > 127 || value > 127 {
            return Err(invalid("MIDI controller and value must be in [0, 127]"));
        }
        Ok(self.input(channel).and_then(|input| {
            let mapping = input
                .controllers
                .iter()
                .find(|mapping| mapping.number == controller)?;
            let value = if value == 127 {
                mapping.maximum
            } else {
                mapping.minimum + (mapping.maximum - mapping.minimum) * f64::from(value) / 127.0
            };
            Some(ControlValue {
                part: &input.part,
                control: &mapping.control,
                value,
            })
        }))
    }

    pub fn pitch_bend(&self, channel: u8, value: i16) -> Result<Option<ControlValue<'_>>, Error> {
        if !(-8192..=8191).contains(&value) {
            return Err(invalid("MIDI pitch bend must be in [-8192, 8191]"));
        }
        Ok(self.input(channel).and_then(|input| {
            let bend = input.pitch_bend.as_ref()?;
            let value = match value {
                -8192 => bend.minimum,
                8191 => bend.maximum,
                v if v < 0 => bend.center + (bend.center - bend.minimum) * f64::from(v) / 8192.0,
                v => bend.center + (bend.maximum - bend.center) * f64::from(v) / 8191.0,
            };
            Some(ControlValue {
                part: &input.part,
                control: &bend.control,
                value,
            })
        }))
    }

    fn input(&self, channel: u8) -> Option<&Input> {
        let slot = channel_index(channel)?;
        self.channels[slot].map(|index| &self.inputs[index])
    }
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Controller {
    number: u8,
    control: Identifier,
    #[serde(default)]
    minimum: f64,
    #[serde(default = "one")]
    maximum: f64,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PitchBend {
    control: Identifier,
    #[serde(default = "negative_one")]
    minimum: f64,
    #[serde(default)]
    center: f64,
    #[serde(default = "one")]
    maximum: f64,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Input {
    channels: Vec<u8>,
    part: Identifier,
    repeated_key_release: RepeatedKeyRelease,
    #[serde(default)]
    controllers: Vec<Controller>,
    #[serde(default)]
    pitch_bend: Option<PitchBend>,
    tuning: Option<ScoreReference>,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PerformanceInputBinding {
    instrument: ScoreReference,
    midi: Vec<Input>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ScoreDefinition {
    #[serde(default = "format")]
    format: String,
    #[serde(default = "version")]
    version: i64,
    #[serde(default = "kind")]
    kind: String,
    name: String,
    title: String,
    #[serde(default)]
    tags: Vec<String>,
    body: PerformanceInputBinding,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Definitions {
    controls: Option<BTreeMap<Identifier, ControlDeclaration>>,
    #[serde(default)]
    tunings: BTreeMap<String, serde_json::Value>,
}

fn format() -> String {
    "recs".into()
}

fn version() -> i64 {
    4
}

fn kind() -> String {
    "performance_binding".into()
}

fn validate_control(
    controls: &BTreeMap<Identifier, ControlDeclaration>,
    control: &Identifier,
    minimum: f64,
    maximum: f64,
) -> Result<(), Error> {
    let name = control.as_str();
    let declaration = controls
        .get(control)
        .ok_or_else(|| invalid(format!("Unknown control: {name}")))?;
    declaration
        .validate_value(minimum)
        .and_then(|()| declaration.validate_value(maximum))
        .map_err(|error| invalid(format!("MIDI control {name}: {error}")))
}

fn channel_index(channel: u8) -> Option<usize> {
    channel
        .checked_sub(1)
        .filter(|index| *index < 16)
        .map(usize::from)
}

fn bipolar_range(minimum: f64, maximum: f64) -> bool {
    minimum >= -1.0 && maximum <= 1.0 && minimum < maximum
}

fn one() -> f64 {
    1.0
}
fn negative_one() -> f64 {
    -1.0
}

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
