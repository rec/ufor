//! Articulation declarations and preparation for the latched sampler profile.

use super::controls::ControlDeclaration;
use crate::envelfo::PreparationLimits;
use crate::error::Error;
use crate::identifier::Identifier;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(try_from = "Definition", into = "Definition")]
pub struct Articulations(Definition);

impl Articulations {
    pub fn ids(&self) -> &[Identifier] {
        &self.0.ids
    }

    pub fn default_articulation(&self) -> Option<&Identifier> {
        self.0.default.as_ref()
    }

    pub fn keys(&self) -> &[KeySwitch] {
        &self.0.keys
    }

    pub fn controls(&self) -> &[ControlSwitch] {
        &self.0.controls
    }

    pub fn validate_controls(
        &self,
        controls: &BTreeMap<Identifier, ControlDeclaration>,
    ) -> Result<(), Error> {
        for switch in &self.0.controls {
            let control = switch.control.as_str();
            let declaration = controls
                .get(&switch.control)
                .ok_or_else(|| invalid(format!("Unknown control: {control}")))?;
            declaration
                .validate_value(switch.minimum_value)
                .and_then(|()| declaration.validate_value(switch.maximum_value))
                .map_err(|error| invalid(format!("Articulation control {control}: {error}")))?;
        }
        Ok(())
    }

    /// Return the switches available to a sampler with per-part latching.
    pub fn latched_keys(&self) -> Result<&[KeySwitch], Error> {
        if !self.0.controls.is_empty() {
            return Err(invalid("control-driven articulations are unsupported"));
        }
        if self
            .0
            .keys
            .iter()
            .any(|key| key.behavior != KeyBehavior::Latched)
        {
            return Err(invalid("momentary keyswitches are unsupported"));
        }
        Ok(&self.0.keys)
    }

    pub(crate) fn check_records(&self, limits: PreparationLimits) -> Result<(), Error> {
        let count = 1 + self.0.ids.len() + self.0.keys.len() + self.0.controls.len();
        if count > limits.max_records() {
            return Err(Error::Limit("articulation records"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct KeySwitch {
    pub key: i64,
    pub articulation: Option<Identifier>,
    #[serde(default)]
    pub behavior: KeyBehavior,
    #[serde(default = "yes")]
    pub consume: bool,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum KeyBehavior {
    #[default]
    Latched,
    Momentary,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ControlSwitch {
    pub control: Identifier,
    pub minimum_value: f64,
    pub maximum_value: f64,
    pub articulation: Identifier,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Definition {
    ids: Vec<Identifier>,
    default: Option<Identifier>,
    #[serde(default)]
    keys: Vec<KeySwitch>,
    #[serde(default)]
    controls: Vec<ControlSwitch>,
}

impl TryFrom<Definition> for Articulations {
    type Error = Error;

    fn try_from(value: Definition) -> Result<Self, Error> {
        let ids: BTreeSet<_> = value.ids.iter().collect();
        if ids.len() != value.ids.len() {
            return Err(invalid("duplicate articulation ID"));
        }
        let mut keys = BTreeSet::new();
        for switch in &value.keys {
            if !keys.insert(switch.key) {
                return Err(invalid("duplicate keyswitch key"));
            }
        }
        let references = value
            .default
            .iter()
            .chain(
                value
                    .keys
                    .iter()
                    .filter_map(|switch| switch.articulation.as_ref()),
            )
            .chain(value.controls.iter().map(|switch| &switch.articulation));
        for id in references {
            if !ids.contains(id) {
                return Err(invalid(format!("Unknown articulation: {}", id.as_str())));
            }
        }
        let mut ranges: Vec<_> = value.controls.iter().collect();
        for range in &ranges {
            if !(-1.0..=1.0).contains(&range.minimum_value)
                || !(range.minimum_value..=1.0).contains(&range.maximum_value)
            {
                return Err(invalid("articulation range must increase within [-1, 1]"));
            }
        }
        ranges.sort_unstable_by(|left, right| {
            left.control
                .cmp(&right.control)
                .then_with(|| left.minimum_value.total_cmp(&right.minimum_value))
        });
        for pair in ranges.windows(2) {
            if pair[0].control == pair[1].control && pair[1].minimum_value <= pair[0].maximum_value
            {
                return Err(invalid(format!(
                    "Overlapping articulation ranges for control {}",
                    pair[0].control.as_str()
                )));
            }
        }
        Ok(Self(value))
    }
}

impl From<Articulations> for Definition {
    fn from(value: Articulations) -> Self {
        value.0
    }
}

fn yes() -> bool {
    true
}

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
