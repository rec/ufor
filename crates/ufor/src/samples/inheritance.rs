//! Resolve authored sampler slot and group settings without reordering bodies.

use crate::{codec, error::Error, identifier::Identifier};
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;
use std::collections::BTreeMap;

#[derive(Clone, Debug, Deserialize)]
#[serde(untagged)]
enum Selection {
    Named(Identifier),
    Switch(bool),
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub(super) struct Layer {
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

impl Layer {
    pub(super) fn with_instrument_envelope(mut self) -> Result<Self, Error> {
        match self.envelope.as_ref().map(|value| value.get()) {
            None => {
                self.envelope = Some(
                    serde_json::from_str(
                        r#"{"segments":[{"duration":0,"to":1}],"release":[{"duration":0,"to":0}]}"#,
                    )
                    .expect("valid default sample instrument envelope"),
                );
            }
            Some("false" | "null") => return Err(invalid("instrument requires an envelope")),
            _ => {}
        }
        Ok(self)
    }

    pub(super) fn group_selection(&self) -> Result<Option<&Identifier>, Error> {
        match &self.selection {
            Some(Selection::Named(value)) => Ok(Some(value)),
            None => Ok(None),
            Some(Selection::Switch(_)) => Err(invalid("group selection must be a name or null")),
        }
    }
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
    let group = group.map(decode_layer).transpose()?;
    resolve_layers(slot, group.as_ref())
}

pub(super) fn resolve_layers(
    slot: Layer,
    group: Option<&Layer>,
) -> Result<ResolvedSlotSettings, Error> {
    let default_group = Layer::default();
    let group = group.unwrap_or(&default_group);
    let inherited_selection = group.group_selection()?.cloned();
    let selection = match slot.selection {
        Some(Selection::Named(value)) => Some(value),
        Some(Selection::Switch(false)) => None,
        Some(Selection::Switch(true)) => return Err(invalid("slot selection cannot be true")),
        None => inherited_selection,
    };
    let envelope = slot.envelope.or_else(|| group.envelope.clone());
    if envelope.as_ref().is_some_and(|value| value.get() == "true") {
        return Err(invalid("envelope cannot be true"));
    }
    let settings = [
        (
            "processing",
            slot.processing.or_else(|| group.processing.clone()),
        ),
        (
            "envelope",
            envelope.filter(|value| !matches!(value.get(), "false" | "null")),
        ),
        ("envelfos", slot.envelfos.or_else(|| group.envelfos.clone())),
        (
            "modulation",
            slot.modulation.or_else(|| group.modulation.clone()),
        ),
        ("bindings", slot.bindings.or_else(|| group.bindings.clone())),
        (
            "event_connections",
            slot.event_connections
                .or_else(|| group.event_connections.clone()),
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
    let value = codec::parse_value(text, codec::Format::Json)?;
    if let Some(fields) = value.as_object() {
        for field in fields.keys() {
            if !matches!(
                field.as_str(),
                "processing"
                    | "envelope"
                    | "envelfos"
                    | "modulation"
                    | "bindings"
                    | "event_connections"
                    | "selection"
            ) {
                return Err(invalid(format!("unknown slot settings field {field}")));
            }
        }
    }
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
