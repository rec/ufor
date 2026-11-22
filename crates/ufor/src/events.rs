//! Portable performance and capture event declarations.

pub mod captured;

use crate::control::tempo;
use crate::error::Error;
use crate::identifier::Identifier;
use crate::number::Rational;
use crate::quantity;
use crate::samples::controls::ControlDeclaration;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use std::collections::BTreeMap;

use captured::{Capture, CapturedPayload};

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
pub struct StoredEvent {
    pub tick: i64,
    pub ordinal: u64,
    #[serde(flatten)]
    pub payload: StoredPayload,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(untagged)]
pub enum StoredPayload {
    Performance(PerformancePayload),
    Captured(CapturedPayload),
}

impl StoredPayload {
    pub fn kind(&self) -> EventKind {
        match self {
            Self::Performance(payload) => match payload.action() {
                Action::Trigger { .. } => EventKind::Trigger,
                Action::Release { .. } => EventKind::Release,
                Action::ControlChange { .. } => EventKind::ControlChange,
                Action::LfoChange { .. } => EventKind::LfoChange,
                Action::EnvelfoChange { .. } => EventKind::EnvelfoChange,
            },
            Self::Captured(payload) => match payload.capture() {
                Capture::Midi { .. } => EventKind::Midi,
                Capture::Ump { .. } => EventKind::Ump,
                Capture::Osc { .. } => EventKind::Osc,
                Capture::Key { .. } => EventKind::Key,
            },
        }
    }

    pub(crate) fn check_toml(&self) -> Result<(), Error> {
        if let Self::Captured(payload) = self {
            payload.check_toml()?;
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EventKind {
    Midi,
    Ump,
    Osc,
    Key,
    Trigger,
    Release,
    ControlChange,
    LfoChange,
    EnvelfoChange,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
pub struct PerformanceEvent {
    pub tick: i64,
    pub ordinal: u64,
    #[serde(flatten)]
    pub payload: PerformancePayload,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(try_from = "Action", into = "Action")]
pub struct PerformancePayload(Action);

impl PerformancePayload {
    pub fn action(&self) -> &Action {
        &self.0
    }

    pub fn validate_controls(
        &self,
        controls: &BTreeMap<Identifier, ControlDeclaration>,
    ) -> Result<(), Error> {
        let validate = |name: &Identifier, value: f64| {
            controls
                .get(name)
                .ok_or_else(|| invalid(format!("Unknown control: {}", name.as_str())))?
                .validate_value(value)
                .map_err(|error| invalid(format!("Control {}: {error}", name.as_str())))
        };
        match &self.0 {
            Action::Trigger { controls, .. } => {
                for (name, value) in controls {
                    validate(name, *value)?;
                }
                Ok(())
            }
            Action::ControlChange { control, value, .. } => validate(control, *value),
            _ => Ok(()),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Action {
    Trigger {
        part: Identifier,
        trigger_id: Identifier,
        key: i64,
        #[serde(default = "one")]
        velocity: f64,
        #[serde(default, deserialize_with = "quantity::deserialize_optional_hertz")]
        pitch_hz: Option<f64>,
        #[serde(default)]
        controls: BTreeMap<Identifier, f64>,
    },
    Release {
        part: Identifier,
        trigger_id: Identifier,
    },
    ControlChange {
        control: Identifier,
        value: f64,
        scope: ControlScope,
        part: Option<Identifier>,
        trigger_id: Option<Identifier>,
    },
    LfoChange {
        name: Identifier,
        action: LfoCommand,
        rate: Option<f64>,
        position: Option<f64>,
        offset: Option<f64>,
    },
    EnvelfoChange {
        #[serde(default)]
        target: EnvelopeTarget,
        name: Option<Identifier>,
        op: Option<Identifier>,
        part: Identifier,
        trigger_id: Identifier,
        action: EnvelopeCommand,
        position: Option<f64>,
        offset: Option<f64>,
        #[serde(
            default,
            deserialize_with = "optional_beats",
            serialize_with = "write_beats"
        )]
        quantize_beats: Option<Rational>,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ControlScope {
    Instrument,
    Part,
    Trigger,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LfoCommand {
    Reset,
    Rate,
    Pause,
    Resume,
    Reverse,
    Seek,
    Shift,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EnvelopeTarget {
    #[default]
    Envelfo,
    Envelope,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EnvelopeCommand {
    Pause,
    Resume,
    Reverse,
    Seek,
    Shift,
    Advance,
}

impl TryFrom<Action> for PerformancePayload {
    type Error = Error;

    fn try_from(record: Action) -> Result<Self, Error> {
        match &record {
            Action::Trigger {
                velocity,
                pitch_hz,
                controls,
                ..
            } => {
                if !(0.0..=1.0).contains(velocity)
                    || pitch_hz.is_some_and(|p| !p.is_finite() || p <= 0.0)
                    || controls.values().any(|value| !(-1.0..=1.0).contains(value))
                {
                    return Err(invalid("Invalid trigger velocity, pitch or control value"));
                }
            }
            Action::ControlChange {
                scope,
                part,
                trigger_id,
                value,
                ..
            } => {
                let expected = match scope {
                    ControlScope::Instrument => (false, false),
                    ControlScope::Part => (true, false),
                    ControlScope::Trigger => (true, true),
                };
                if (part.is_some(), trigger_id.is_some()) != expected
                    || !(-1.0..=1.0).contains(value)
                {
                    return Err(invalid("Invalid control address or value"));
                }
            }
            Action::LfoChange {
                action,
                rate,
                position,
                offset,
                ..
            } => {
                if (*action == LfoCommand::Rate) != rate.is_some()
                    || rate.is_some_and(|r| !r.is_finite() || r < 0.0)
                {
                    return Err(invalid("Invalid LFO rate payload"));
                }
                validate_command(
                    *action == LfoCommand::Seek,
                    *action == LfoCommand::Shift,
                    *position,
                    *offset,
                )?;
            }
            Action::EnvelfoChange {
                target,
                name,
                op,
                action,
                position,
                offset,
                quantize_beats,
                ..
            } => {
                let addressed = match target {
                    EnvelopeTarget::Envelfo => name.is_some() && op.is_none(),
                    EnvelopeTarget::Envelope => name.is_none(),
                };
                if !addressed || quantize_beats.is_some_and(|division| division.numerator() <= 0) {
                    return Err(invalid("Invalid Envelfo address or beat division"));
                }
                validate_command(
                    *action == EnvelopeCommand::Seek,
                    *action == EnvelopeCommand::Shift,
                    *position,
                    *offset,
                )?;
            }
            Action::Release { .. } => {}
        }
        Ok(Self(record))
    }
}

impl From<PerformancePayload> for Action {
    fn from(payload: PerformancePayload) -> Self {
        payload.0
    }
}

fn validate_command(
    seek: bool,
    shift: bool,
    position: Option<f64>,
    offset: Option<f64>,
) -> Result<(), Error> {
    if seek != position.is_some()
        || shift != offset.is_some()
        || position.is_some_and(|p| !(0.0..=1.0).contains(&p))
        || offset.is_some_and(|o| !o.is_finite())
    {
        return Err(invalid("Invalid seek or shift payload"));
    }
    Ok(())
}

fn optional_beats<'de, D: Deserializer<'de>>(d: D) -> Result<Option<Rational>, D::Error> {
    #[derive(Deserialize)]
    struct Beats(#[serde(deserialize_with = "tempo::beats")] Rational);

    Option::<Beats>::deserialize(d).map(|value| value.map(|beats| beats.0))
}

fn write_beats<S: Serializer>(value: &Option<Rational>, serializer: S) -> Result<S::Ok, S::Error> {
    match value {
        Some(value) => serializer.collect_str(value),
        None => serializer.serialize_none(),
    }
}

fn one() -> f64 {
    1.0
}

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
