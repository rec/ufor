//! Ordered mapping and sampler predicates against an already-resolved event.
use super::playback::Mapping;
use crate::{error::Error, identifier::Identifier, quantity};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Trigger {
    #[default]
    Start,
    Control,
    Release,
    LogicalRelease,
    SustainPress,
    SustainRelease,
}

impl Trigger {
    pub(super) fn as_str(self) -> &'static str {
        match self {
            Self::Start => "start",
            Self::Control => "control",
            Self::Release => "release",
            Self::LogicalRelease => "logical_release",
            Self::SustainPress => "sustain_press",
            Self::SustainRelease => "sustain_release",
        }
    }

    pub(crate) fn is_sustain(self) -> bool {
        matches!(self, Self::SustainPress | Self::SustainRelease)
    }
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct VoiceMapping {
    pub(crate) name: Identifier,
    pub(crate) mapping: Mapping,
    #[serde(default)]
    pub(crate) trigger: Trigger,
}

impl VoiceMapping {
    pub(crate) fn validate(&self) -> Result<(), Error> {
        if self.trigger.is_sustain() != self.mapping.event_key().is_some() {
            return Err(invalid("event_key is required only for sustain voices"));
        }
        Ok(())
    }

    pub(crate) fn matches(&self, trigger: Trigger, key: i64, velocity: f64) -> bool {
        self.trigger == trigger && matches_note(&self.mapping, trigger, Some(key), velocity)
    }
}

/// Synth-family voice mappings in instrument declaration order.
#[derive(Debug)]
pub struct VoiceEligibility(Vec<VoiceMapping>);

impl VoiceEligibility {
    pub(crate) fn decode(value: serde_json::Value, maximum: usize) -> Result<Self, Error> {
        let voices: Vec<VoiceMapping> =
            serde_json::from_value(value).map_err(|error| invalid(error.to_string()))?;
        quantity::record_budget(voices.len(), maximum)?;
        let mut names = BTreeSet::new();
        for voice in &voices {
            if !names.insert(&voice.name) {
                return Err(invalid("duplicate voice name"));
            }
            voice.validate()?;
        }
        Ok(Self(voices))
    }

    /// Return all mapped voices in declaration order.
    pub fn matching_voices(
        &self,
        trigger: Trigger,
        key: i64,
        velocity: f64,
    ) -> impl Iterator<Item = &Identifier> {
        self.0
            .iter()
            .filter_map(move |voice| voice.matches(trigger, key, velocity).then_some(&voice.name))
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Context {
    pub trigger: Trigger,
    pub key: Option<i64>,
    pub velocity: f64,
    pub active_articulation: Option<Identifier>,
    pub held_keys: Vec<i64>,
    pub previous_key: Option<i64>,
    pub controls: BTreeMap<Identifier, f64>,
    pub control_event: Option<(Identifier, f64)>,
    pub note_on_count: u64,
    pub random_value: f64,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Slot {
    pub(super) name: Identifier,
    mapping: Mapping,
    #[serde(default)]
    pub(super) trigger: Trigger,
    #[serde(default)]
    articulations: Vec<Identifier>,
    #[serde(default)]
    key_conditions: Vec<KeyCondition>,
    #[serde(default)]
    previous_key: Option<i64>,
    #[serde(default)]
    control_conditions: Vec<ControlCondition>,
    #[serde(default)]
    control_trigger: Option<ControlTrigger>,
    #[serde(default)]
    sequence: Option<Sequence>,
    #[serde(default)]
    random_range: Option<RandomRange>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct KeyCondition {
    key: i64,
    pressed: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ControlCondition {
    control: Identifier,
    #[serde(default)]
    minimum_value: f64,
    #[serde(default = "one")]
    maximum_value: f64,
}

impl ControlCondition {
    fn valid(&self) -> bool {
        -1.0 <= self.minimum_value
            && self.minimum_value <= self.maximum_value
            && self.maximum_value <= 1.0
    }

    fn accepts(&self, value: f64) -> bool {
        (self.minimum_value..=self.maximum_value).contains(&value)
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ControlTrigger {
    control: Identifier,
    #[serde(default)]
    minimum_value: f64,
    #[serde(default = "one")]
    maximum_value: f64,
    pitch_hz: f64,
    velocity: f64,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Sequence {
    length: u64,
    position: u64,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RandomRange {
    #[serde(default)]
    minimum: f64,
    #[serde(default = "one")]
    maximum: f64,
}

/// Validated slot predicates in instrument declaration order.
#[derive(Debug)]
pub struct Eligibility(Vec<Slot>);

impl Eligibility {
    pub(crate) fn decode(value: serde_json::Value, maximum: usize) -> Result<Self, Error> {
        let slots: Vec<Slot> =
            serde_json::from_value(value).map_err(|error| invalid(error.to_string()))?;
        quantity::record_budget(slots.len(), maximum)?;
        Self::prepare(slots)
    }

    pub(super) fn prepare(slots: Vec<Slot>) -> Result<Self, Error> {
        let mut names = BTreeSet::new();
        for slot in &slots {
            if !names.insert(&slot.name) {
                return Err(invalid("duplicate sample slot"));
            }
            let valid_mapping = if slot.trigger.is_sustain() {
                slot.mapping.has_sustain_mapping()
            } else {
                slot.mapping.event_key().is_none()
            };
            if (slot.trigger == Trigger::Control) != slot.control_trigger.is_some()
                || slot.trigger != Trigger::Start && slot.sequence.is_some()
                || slot.trigger == Trigger::Control && slot.random_range.is_some()
                || !valid_mapping
            {
                return Err(invalid(
                    "invalid eligibility declaration for sample trigger",
                ));
            }
            if slot
                .sequence
                .as_ref()
                .is_some_and(|s| s.position == 0 || s.position > s.length)
                || slot.random_range.as_ref().is_some_and(|r| {
                    !(0.0 <= r.minimum && r.minimum < r.maximum && r.maximum <= 1.0)
                })
            {
                return Err(invalid("invalid sample sequence or random range"));
            }
            if slot.control_conditions.iter().any(|c| !c.valid())
                || slot.control_trigger.as_ref().is_some_and(|c| {
                    !(-1.0 <= c.minimum_value
                        && c.minimum_value <= c.maximum_value
                        && c.maximum_value <= 1.0
                        && c.pitch_hz.is_finite()
                        && c.pitch_hz > 0.0
                        && (0.0..=1.0).contains(&c.velocity))
                })
            {
                return Err(invalid("invalid sample control condition"));
            }
        }
        Ok(Self(slots))
    }

    pub fn matching_slots<'a>(&'a self, context: &Context) -> Result<Vec<&'a Identifier>, Error> {
        if !context.velocity.is_finite() || !(0.0..=1.0).contains(&context.random_value) {
            return Err(invalid(
                "sample velocity must be finite and random draw in [0, 1]",
            ));
        }
        let held: BTreeSet<_> = context.held_keys.iter().copied().collect();
        let mut matches = Vec::new();
        for slot in &self.0 {
            if slot.trigger != context.trigger
                || !matches_note(
                    &slot.mapping,
                    context.trigger,
                    context.key,
                    context.velocity,
                )
                || slot.control_trigger.as_ref().is_some_and(|trigger| {
                    !context
                        .control_event
                        .as_ref()
                        .is_some_and(|(control, value)| {
                            control == &trigger.control
                                && (trigger.minimum_value..=trigger.maximum_value).contains(value)
                        })
                })
                || (!slot.articulations.is_empty()
                    && !context
                        .active_articulation
                        .as_ref()
                        .is_some_and(|a| slot.articulations.contains(a)))
                || slot
                    .key_conditions
                    .iter()
                    .any(|c| held.contains(&c.key) != c.pressed)
                || slot
                    .previous_key
                    .is_some_and(|key| Some(key) != context.previous_key)
            {
                continue;
            }
            let mut controls_match = true;
            for condition in &slot.control_conditions {
                let value = context.controls.get(&condition.control).ok_or_else(|| {
                    invalid(format!(
                        "missing sample control {}",
                        condition.control.as_str()
                    ))
                })?;
                if !condition.accepts(*value) {
                    controls_match = false;
                    break;
                }
            }
            if !controls_match
                || slot.sequence.as_ref().is_some_and(|seq| {
                    let position = context
                        .note_on_count
                        .checked_sub(1)
                        .map_or(seq.length, |count| count % seq.length + 1);
                    position != seq.position
                })
                || slot
                    .random_range
                    .as_ref()
                    .is_some_and(|r| !(r.minimum..r.maximum).contains(&context.random_value))
            {
                continue;
            }
            matches.push(&slot.name);
        }
        Ok(matches)
    }
}

fn matches_note(mapping: &Mapping, trigger: Trigger, key: Option<i64>, velocity: f64) -> bool {
    key.is_none_or(|key| mapping.accepts_note(key, velocity))
        && (!trigger.is_sustain() || mapping.event_key() == key)
}

fn one() -> f64 {
    1.0
}

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
