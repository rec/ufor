//! Prepare slot predicates, inherited settings and playback from an authored JSON body.

use super::eligibility::{Eligibility, Slot, Trigger};
use super::inheritance::{Layer, ResolvedSlotSettings, resolve_layers};
use super::playback::{Playback, PlaybackMode, ResolvedSlotPlayback, Slice, SlotPlayback};
use crate::{codec, envelfo::PreparationLimits, error::Error, identifier::Identifier};
use serde::Deserialize;
use serde_json::value::RawValue;
use std::collections::BTreeMap;

/// Slot data used by sampler traces and render preparation.
#[derive(Debug)]
pub struct PreparedSlots {
    eligibility: Eligibility,
    settings: BTreeMap<Identifier, ResolvedSlotSettings>,
    playback: BTreeMap<String, ResolvedSlotPlayback>,
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
        let mut slices = BTreeMap::new();
        for slice in &instrument.slices {
            if slices.insert(slice.name(), slice).is_some() {
                return Err(invalid("duplicate sample slice name"));
            }
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
        let mut playback = BTreeMap::new();
        for raw in instrument.slots {
            let slot: SlotDeclaration = decode(raw.get())?;
            let slice = slices
                .get(&slot.slice)
                .ok_or_else(|| invalid(format!("Unknown slice: {}", slot.slice.as_str())))?;
            let traversal = slot.playback.resolve(instrument.settings.playback)?;
            if slot.predicate.trigger != Trigger::Start
                && traversal.playback.mode != PlaybackMode::OneShot
            {
                return Err(invalid(
                    "release/sustain/control slots require one_shot playback",
                ));
            }
            // Asset inventory checks that the authored slice fits the decoded asset.
            slice.validate_playback(
                traversal.playback,
                slice.end_frame(),
                traversal.additional_plays,
            )?;
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
            playback.insert(slot.predicate.name.as_str().to_owned(), traversal);
            slots.push(slot.predicate);
        }
        Ok(Self {
            eligibility: Eligibility::prepare(slots)?,
            settings,
            playback,
        })
    }

    pub fn eligibility(&self) -> &Eligibility {
        &self.eligibility
    }

    pub fn settings(&self) -> &BTreeMap<Identifier, ResolvedSlotSettings> {
        &self.settings
    }

    pub fn playback(&self, slot: &str) -> Option<ResolvedSlotPlayback> {
        self.playback.get(slot).copied()
    }
}

#[derive(Deserialize)]
struct Declaration<'a> {
    #[serde(default, rename = "kind")]
    _kind: Kind,
    slices: Vec<Slice>,
    #[serde(default)]
    settings: PlaybackSettings,
    #[serde(default, borrow)]
    groups: Vec<&'a RawValue>,
    #[serde(borrow)]
    slots: Vec<&'a RawValue>,
}

#[derive(Default, Deserialize)]
struct PlaybackSettings {
    #[serde(default)]
    playback: Playback,
}

#[derive(Default, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Kind {
    #[default]
    SampleInstrument,
}

#[derive(Deserialize)]
struct GroupIdentity {
    name: Identifier,
}

#[derive(Deserialize)]
struct SlotDeclaration {
    slice: Identifier,
    group: Option<Identifier>,
    #[serde(default)]
    playback: SlotPlayback,
    #[serde(flatten)]
    predicate: Slot,
}

fn decode<'a, T: Deserialize<'a>>(text: &'a str) -> Result<T, Error> {
    serde_json::from_str(text).map_err(|error| invalid(error.to_string()))
}

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
