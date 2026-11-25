//! Context shared by sampler instrument, group and effective slot settings.

use super::{Slot, Trigger, invalid};
use crate::control::Scope;
use crate::envelfo::PreparationLimits;
use crate::error::Error;
use crate::identifier::Identifier;
use crate::samples::controls::ControlDeclaration;
use crate::samples::inheritance::ResolvedSlotSettings;
use crate::samples::processing::{Binding, EventKind, SoundSettings, SoundWire};
use crate::samples::routing::validate_sampler_spatial;
use std::collections::BTreeMap;

pub(super) fn decode(
    layer: &ResolvedSlotSettings,
    controls: &BTreeMap<Identifier, ControlDeclaration>,
    limits: PreparationLimits,
) -> Result<SoundSettings, Error> {
    let text =
        serde_json::to_string(&layer.settings).map_err(|error| invalid(error.to_string()))?;
    let wire: SoundWire =
        serde_json::from_str(&text).map_err(|error| invalid(error.to_string()))?;
    wire.prepare(limits, Some(controls), |_| None)
}

pub(super) fn validate_common(settings: &SoundSettings) -> Result<(), Error> {
    for parameter in settings.modulation().parameters() {
        let name = parameter.target().name().as_str();
        if parameter.scope() != Scope::Voice
            && (name == "processing" || name.starts_with("eq-") || name.starts_with("filter-"))
        {
            return Err(invalid("Instrument processing is per voice, before mixing"));
        }
    }
    Ok(())
}

pub(super) fn validate_layers(
    common: &SoundSettings,
    effective: &SoundSettings,
    slot: &Slot,
) -> Result<(), Error> {
    let common_processing = common.processing();
    let slot_processing = effective.processing();
    if !common_processing.filters().is_empty()
        && !slot_processing.filters().is_empty()
        && common_processing.filter_order() != slot_processing.filter_order()
    {
        return Err(invalid("active filter chains require the same order"));
    }
    if effective
        .envelfos()
        .iter()
        .any(|(_, generator)| generator.settings().scope() != Scope::Voice)
    {
        return Err(invalid("Slot envelfos must have voice scope"));
    }
    if effective
        .modulation()
        .parameters()
        .iter()
        .any(|parameter| parameter.scope() != Scope::Voice)
    {
        return Err(invalid("Slot parameters must have voice scope"));
    }
    for settings in [common, effective] {
        let mapping = slot.mapping.note_range();
        for binding in settings.bindings() {
            if let Binding::Event(binding) = binding {
                if binding.kind() != EventKind::Key {
                    continue;
                }
                if slot.trigger == Trigger::Control {
                    return Err(invalid("Control-triggered voices have no note key"));
                }
                let source = settings
                    .modulation()
                    .sources()
                    .iter()
                    .find(|source| source.name() == binding.name())
                    .expect("validated binding source");
                if source.minimum() > *mapping.start() as f64
                    || (*mapping.end() as f64) > source.maximum()
                {
                    return Err(invalid("NoteKey source domain must cover the slot mapping"));
                }
            }
        }
    }
    validate_sampler_spatial(common, effective)
}
