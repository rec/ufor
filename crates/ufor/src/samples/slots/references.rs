//! Relationships among alternatives in one sampler selection and trigger class.

use super::{SlotDeclaration, Trigger, invalid};
use crate::{error::Error, identifier::Identifier};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Default)]
pub(super) struct TakeReferences {
    groups: BTreeMap<(Identifier, Trigger), Group>,
}

#[derive(Default)]
struct Group {
    sustain_key: Option<i64>,
    ordinary: bool,
    takes: BTreeMap<Identifier, BTreeSet<Identifier>>,
}

impl TakeReferences {
    pub(super) fn add(
        &mut self,
        slot: &SlotDeclaration,
        selection: Option<&Identifier>,
    ) -> Result<(), Error> {
        let trigger = slot.predicate.trigger;
        if slot.take.is_none() && (slot.microphone.is_some() || slot.alignment_frames != 0) {
            return Err(invalid("microphone and alignment_frames require take"));
        }
        let Some(selection) = selection else {
            if slot.take.is_some() {
                return Err(invalid(
                    "Linked takes require a selection and microphone identity",
                ));
            }
            return Ok(());
        };
        if trigger == Trigger::Control {
            return Err(invalid(
                "control triggers do not support alternate selections",
            ));
        }
        let group = self.groups.entry((selection.clone(), trigger)).or_default();
        if trigger.is_sustain() {
            let key = slot.predicate.mapping.event_key();
            if group.sustain_key.is_some() && group.sustain_key != key {
                return Err(invalid(format!(
                    "Selection {}: sustain alternatives must share event_key",
                    selection.as_str()
                )));
            }
            group.sustain_key = key;
        }
        if let Some(take) = &slot.take {
            let microphone = slot.microphone.as_ref().ok_or_else(|| {
                invalid("Linked takes require a selection and microphone identity")
            })?;
            if !group
                .takes
                .entry(take.clone())
                .or_default()
                .insert(microphone.clone())
            {
                return Err(invalid(format!(
                    "duplicate microphone identity in take {}",
                    take.as_str()
                )));
            }
        } else {
            group.ordinary = true;
        }
        Ok(())
    }

    pub(super) fn validate_microphones(&self) -> Result<(), Error> {
        for ((selection, _), group) in &self.groups {
            let mut takes = group.takes.iter();
            let Some((_, microphones)) = takes.next() else {
                continue;
            };
            if group.ordinary {
                return Err(invalid(format!(
                    "Selection {} mixes linked and ordinary takes",
                    selection.as_str()
                )));
            }
            for (take, other) in takes {
                if other != microphones {
                    return Err(invalid(format!(
                        "Selection {}: take {} has different microphones",
                        selection.as_str(),
                        take.as_str()
                    )));
                }
            }
        }
        Ok(())
    }
}
