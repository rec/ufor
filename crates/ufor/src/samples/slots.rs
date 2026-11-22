//! Prepare slot predicates and inherited settings from an authored JSON body.

use super::eligibility::{Eligibility, Slot};
use super::inheritance::{Layer, ResolvedSlotSettings, resolve_layers};
use crate::{codec, envelfo::PreparationLimits, error::Error, identifier::Identifier};
use serde::Deserialize;
use serde_json::value::RawValue;
use std::collections::BTreeMap;

/// Slot data used by sampler traces and render preparation.
#[derive(Debug)]
pub struct PreparedSlots {
    eligibility: Eligibility,
    settings: BTreeMap<Identifier, ResolvedSlotSettings>,
}

impl PreparedSlots {
    /// Read the slot and group declarations from a sampler body.
    ///
    /// The rest of the instrument is consumed by its respective preparation
    /// stages. Raw setting fragments preserve nested declaration order.
    pub fn from_json(text: &str, limits: PreparationLimits) -> Result<Self, Error> {
        codec::parse_value(text, codec::Format::Json)?;
        let instrument: Declaration<'_> = decode(text)?;
        if instrument.slots.is_empty() {
            return Err(invalid("sample instrument requires at least one slot"));
        }
        if instrument.slots.len() > limits.max_records() {
            return Err(Error::Limit("sample slot records"));
        }
        let mut groups = BTreeMap::new();
        for raw in instrument.groups {
            let identity: GroupIdentity = decode(raw.get())?;
            if groups
                .insert(identity.name, decode::<Layer>(raw.get())?)
                .is_some()
            {
                return Err(invalid("duplicate sample slot group"));
            }
        }
        let mut slots = Vec::with_capacity(instrument.slots.len());
        let mut settings = BTreeMap::new();
        for raw in instrument.slots {
            let slot: SlotDeclaration = decode(raw.get())?;
            let group = slot
                .group
                .as_ref()
                .map(|name| {
                    groups.get(name).ok_or_else(|| {
                        invalid(format!(
                            "Slot {}: unknown group {}",
                            slot.predicate.name.as_str(),
                            name.as_str()
                        ))
                    })
                })
                .transpose()?;
            let resolved = resolve_layers(decode(raw.get())?, group)?;
            settings.insert(slot.predicate.name.clone(), resolved);
            slots.push(slot.predicate);
        }
        Ok(Self {
            eligibility: Eligibility::prepare(slots)?,
            settings,
        })
    }

    pub fn eligibility(&self) -> &Eligibility {
        &self.eligibility
    }

    pub fn settings(&self) -> &BTreeMap<Identifier, ResolvedSlotSettings> {
        &self.settings
    }
}

#[derive(Deserialize)]
struct Declaration<'a> {
    #[serde(default, rename = "kind")]
    _kind: Kind,
    #[serde(default, borrow)]
    groups: Vec<&'a RawValue>,
    #[serde(borrow)]
    slots: Vec<&'a RawValue>,
}

#[derive(Default, Deserialize)]
#[serde(rename_all = "snake_case")]
enum Kind {
    #[default]
    SampleInstrument,
}

#[derive(Deserialize)]
struct GroupIdentity {
    name: Identifier,
}

#[derive(Deserialize)]
struct SlotDeclaration {
    group: Option<Identifier>,
    #[serde(flatten)]
    predicate: Slot,
}

fn decode<'a, T: Deserialize<'a>>(text: &'a str) -> Result<T, Error> {
    serde_json::from_str(text).map_err(|error| invalid(error.to_string()))
}

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
