//! Prepare slot predicates, inherited settings and playback from an authored JSON body.

use super::articulations::{Articulations, KeySwitch};
use super::controls::ControlDeclaration;
use super::crossfade::Crossfade;
use super::eligibility::{Eligibility, Slot, Trigger};
use super::inheritance::{Layer, ResolvedSlotSettings, resolve_layers};
use super::playback::{Playback, PlaybackMode, ResolvedSlotPlayback, Slice, SlotPlayback};
use super::selection::Selection;
use crate::voice_admission::{Choke, VoicePool};
use crate::voice_release::Sustain;
use crate::{codec, envelfo::PreparationLimits, error::Error, identifier::Identifier};
use serde::Deserialize;
use serde_json::value::RawValue;
use std::collections::{BTreeMap, BTreeSet};

mod references;
mod sound;
use references::TakeReferences;

/// Slot data used by sampler traces and render preparation.
#[derive(Debug)]
pub struct PreparedSlots {
    eligibility: Eligibility,
    settings: BTreeMap<Identifier, ResolvedSlotSettings>,
    playback: BTreeMap<String, ResolvedSlotPlayback>,
    controls: BTreeMap<Identifier, ControlDeclaration>,
    articulations: Option<Articulations>,
    sustain_pressed: bool,
    limits: PreparationLimits,
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
        let authored_settings: InstrumentSettings = instrument
            .settings
            .map(|raw| decode(raw.get()))
            .transpose()?
            .unwrap_or_default();
        let selections = unique_names(
            authored_settings.selections.iter().map(|item| &item.name),
            "selection",
        )?;
        let pools = unique_names(
            instrument.voice_pools.iter().map(|item| &item.name),
            "voice pool",
        )?;
        let controls = &authored_settings.controls;
        let common_layer: Layer = instrument
            .settings
            .map(|raw| decode(raw.get()))
            .transpose()?
            .unwrap_or_default();
        let common = sound::decode(
            &resolve_layers(common_layer.with_instrument_envelope()?, None)?,
            controls,
            limits,
        )?;
        sound::validate_common(&common)?;
        let articulations = authored_settings
            .articulations
            .as_ref()
            .map_or(&[][..], Articulations::ids);
        if let Some(declarations) = &authored_settings.articulations {
            declarations.validate_controls(controls)?;
        }
        let sustain_pressed = if let Some(sustain) = &authored_settings.sustain {
            let declaration = controls.get(sustain.control()).ok_or_else(|| {
                invalid(format!(
                    "Unknown sustain control: {}",
                    sustain.control().as_str()
                ))
            })?;
            sustain.initially_pressed(declaration)?
        } else {
            false
        };
        let mut groups = BTreeMap::new();
        for raw in instrument.groups {
            let identity: GroupIdentity = decode(raw.get())?;
            let layer: Layer = decode(raw.get())?;
            sound::decode(&resolve_layers(layer.clone(), None)?, controls, limits)?;
            if layer
                .group_selection()?
                .is_some_and(|name| !selections.contains(name))
            {
                return Err(invalid(format!(
                    "Slot group {}: unknown selection",
                    identity.name.as_str()
                )));
            }
            if groups.insert(identity.name, layer).is_some() {
                return Err(invalid("duplicate sample slot group"));
            }
        }
        let mut slots = Vec::with_capacity(instrument.slots.len());
        let mut settings = BTreeMap::new();
        let mut playback = BTreeMap::new();
        let declarations: Vec<SlotDeclaration> = instrument
            .slots
            .iter()
            .map(|raw| decode(raw.get()))
            .collect::<Result<_, _>>()?;
        let choke_groups: BTreeSet<_> = declarations
            .iter()
            .filter_map(|slot| slot.choke_group.clone())
            .collect();
        let mut takes = TakeReferences::default();
        for (raw, slot) in instrument.slots.into_iter().zip(declarations) {
            slot.predicate
                .validate_references(controls, articulations)?;
            if slot.predicate.trigger == Trigger::Control && !slot.crossfades.is_empty() {
                return Err(invalid("control triggers do not support crossfades"));
            }
            Crossfade::validate_slot(&slot.crossfades, &slot.predicate.mapping, controls)?;
            if slot
                .voice_pool
                .as_ref()
                .is_some_and(|pool| !pools.contains(pool))
            {
                return Err(invalid(format!(
                    "Slot {}: unknown voice pool",
                    slot.predicate.name.as_str()
                )));
            }
            let chokes = unique_names(slot.chokes.iter().map(Choke::group), "choke target")?;
            if chokes.iter().any(|group| !choke_groups.contains(*group)) {
                return Err(invalid(format!(
                    "Slot {}: unknown choke group",
                    slot.predicate.name.as_str()
                )));
            }
            let slice = slices
                .get(&slot.slice)
                .ok_or_else(|| invalid(format!("Unknown slice: {}", slot.slice.as_str())))?;
            let traversal = slot.playback.resolve(authored_settings.playback)?;
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
            let effective = sound::decode(&resolved, controls, limits)?;
            sound::validate_layers(&common, &effective, &slot.predicate)?;
            if resolved
                .selection
                .as_ref()
                .is_some_and(|name| !selections.contains(name))
            {
                return Err(invalid(format!(
                    "Slot {}: unknown selection",
                    slot.predicate.name.as_str()
                )));
            }
            if slot.predicate.trigger.is_sustain() && authored_settings.sustain.is_none() {
                return Err(invalid("sustain triggers require a sustain control"));
            }
            takes.add(&slot, resolved.selection.as_ref())?;
            settings.insert(slot.predicate.name.clone(), resolved);
            playback.insert(slot.predicate.name.as_str().to_owned(), traversal);
            slots.push(slot.predicate);
        }
        takes.validate_microphones()?;
        Ok(Self {
            eligibility: Eligibility::prepare(slots)?,
            settings,
            playback,
            controls: authored_settings.controls,
            articulations: authored_settings.articulations,
            sustain_pressed,
            limits,
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

    pub fn controls(&self) -> &BTreeMap<Identifier, ControlDeclaration> {
        &self.controls
    }

    pub fn sustain_pressed(&self) -> bool {
        self.sustain_pressed
    }

    pub fn latched_keys(&self) -> Result<&[KeySwitch], Error> {
        self.articulations
            .as_ref()
            .map_or(Ok(&[]), |articulations| {
                articulations.check_records(self.limits)?;
                articulations.latched_keys()
            })
    }
}

#[derive(Deserialize)]
struct Declaration<'a> {
    #[serde(default, rename = "kind")]
    _kind: Kind,
    slices: Vec<Slice>,
    #[serde(default, borrow)]
    settings: Option<&'a RawValue>,
    #[serde(default)]
    voice_pools: Vec<VoicePool>,
    #[serde(default, borrow)]
    groups: Vec<&'a RawValue>,
    #[serde(borrow)]
    slots: Vec<&'a RawValue>,
}

#[derive(Default, Deserialize)]
struct InstrumentSettings {
    #[serde(default)]
    playback: Playback,
    #[serde(default)]
    selections: Vec<Selection>,
    #[serde(default)]
    controls: BTreeMap<Identifier, ControlDeclaration>,
    articulations: Option<Articulations>,
    sustain: Option<Sustain>,
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
    voice_pool: Option<Identifier>,
    choke_group: Option<Identifier>,
    #[serde(default)]
    chokes: Vec<Choke>,
    #[serde(default)]
    crossfades: Vec<Crossfade>,
    take: Option<Identifier>,
    microphone: Option<Identifier>,
    #[serde(default)]
    alignment_frames: i64,
    #[serde(flatten)]
    predicate: Slot,
}

fn unique_names<'a>(
    names: impl Iterator<Item = &'a Identifier>,
    category: &str,
) -> Result<BTreeSet<&'a Identifier>, Error> {
    let mut unique = BTreeSet::new();
    for name in names {
        if !unique.insert(name) {
            return Err(invalid(format!("duplicate {category}: {}", name.as_str())));
        }
    }
    Ok(unique)
}

fn decode<'a, T: Deserialize<'a>>(text: &'a str) -> Result<T, Error> {
    serde_json::from_str(text).map_err(|error| invalid(error.to_string()))
}

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
