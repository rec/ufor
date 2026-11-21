//! Resolve authored sampler slot and group settings without reordering bodies.

use crate::{codec, error::Error, identifier::Identifier};
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;
use std::collections::BTreeMap;

#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum Selection {
    Named(Identifier),
    Switch(bool),
}

#[derive(Debug, Default, Deserialize)]
#[serde(default, deny_unknown_fields)]
struct Layer {
    #[serde(deserialize_with = "present_value")]
    processing: Option<Box<RawValue>>,
    #[serde(deserialize_with = "present_value")]
    envelope: Option<Box<RawValue>>,
    #[serde(deserialize_with = "present_value")]
    envelfos: Option<Box<RawValue>>,
    #[serde(deserialize_with = "present_value")]
    modulation: Option<Box<RawValue>>,
    #[serde(deserialize_with = "present_value")]
    bindings: Option<Box<RawValue>>,
    #[serde(deserialize_with = "present_value")]
    event_connections: Option<Box<RawValue>>,
    selection: Option<Selection>,
}

#[derive(Debug, Serialize)]
pub struct ResolvedSlotSettings {
    /// Canonical field fragments in their original nested declaration order.
    pub settings: BTreeMap<&'static str, Box<RawValue>>,
    pub selection: Option<Identifier>,
}

/// Resolve the six SoundSettings categories and selection for a projected slot.
///
/// Each JSON object contains only SoundSettings categories and selection.
/// Omitted categories can inherit. A slot's false or null envelope clears it.
/// The selected bodies can be decoded with the existing SoundSettings codec.
pub fn resolve_slot_settings(
    slot: &str,
    group: Option<&str>,
) -> Result<ResolvedSlotSettings, Error> {
    let slot = decode_layer(slot)?;
    let group = group.map(decode_layer).transpose()?.unwrap_or_default();
    let inherited_selection = match group.selection {
        Some(Selection::Named(value)) => Some(value),
        None => None,
        Some(Selection::Switch(_)) => {
            return Err(invalid("group selection must be a name or null"));
        }
    };
    let selection = match slot.selection {
        Some(Selection::Named(value)) => Some(value),
        Some(Selection::Switch(false)) => None,
        Some(Selection::Switch(true)) => return Err(invalid("slot selection cannot be true")),
        None => inherited_selection,
    };
    let envelope = slot.envelope.or(group.envelope);
    if envelope.as_ref().is_some_and(|value| value.get() == "true") {
        return Err(invalid("envelope cannot be true"));
    }
    let settings = [
        ("processing", slot.processing.or(group.processing)),
        (
            "envelope",
            envelope.filter(|value| !matches!(value.get(), "false" | "null")),
        ),
        ("envelfos", slot.envelfos.or(group.envelfos)),
        ("modulation", slot.modulation.or(group.modulation)),
        ("bindings", slot.bindings.or(group.bindings)),
        (
            "event_connections",
            slot.event_connections.or(group.event_connections),
        ),
    ]
    .into_iter()
    .filter_map(|(name, value)| value.map(|value| (name, value)))
    .collect();
    Ok(ResolvedSlotSettings {
        settings,
        selection,
    })
}

fn decode_layer(text: &str) -> Result<Layer, Error> {
    codec::parse_value(text, codec::Format::Json)?;
    serde_json::from_str(text).map_err(|error| invalid(error.to_string()))
}

fn present_value<'de, D: serde::Deserializer<'de>>(
    decoder: D,
) -> Result<Option<Box<RawValue>>, D::Error> {
    Box::<RawValue>::deserialize(decoder).map(Some)
}

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
