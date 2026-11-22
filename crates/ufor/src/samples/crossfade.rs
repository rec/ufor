//! Sample layer fades for keys, velocity, and resolved controls.
use super::controls::ControlDeclaration;
use crate::control::Polarity;
use crate::number::Rational;
use crate::time::duration_frames;
use crate::{error::Error, identifier::Identifier, quantity};
use serde::{Deserialize, Deserializer, Serialize};
use std::collections::BTreeMap;
use std::f64::consts::PI;

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(try_from = "Definition", into = "Definition")]
pub struct Crossfade(Definition);

impl Crossfade {
    /// An onset weight for latched fades. Control fades are evaluated separately.
    pub fn onset_weight(&self, key: Option<i64>, velocity: f64) -> Result<Option<f64>, Error> {
        let (position, shape) = match &self.0 {
            Definition::Key { start, end, shape } => {
                let key =
                    key.ok_or_else(|| invalid("Key crossfade requires resolved onset key"))?;
                let position =
                    key.clamp(*start, *end).abs_diff(*start) as f64 / end.abs_diff(*start) as f64;
                (position, shape)
            }
            Definition::Velocity { start, end, shape } => {
                ((quantity::finite(velocity)? - start) / (end - start), shape)
            }
            Definition::Control { .. } => return Ok(None),
        };
        Ok(Some(shape.weight(position)))
    }

    pub fn control_route(&self) -> Option<(f64, f64, bool, bool)> {
        match &self.0 {
            Definition::Control {
                start, end, shape, ..
            } => Some((*start, *end, shape.inward(), shape.equal_power())),
            _ => None,
        }
    }

    /// Resolve a live control fade using the instrument's control declarations.
    /// Latched key and velocity fades have no live control route.
    pub fn prepare_control<'a>(
        &'a self,
        controls: &BTreeMap<Identifier, ControlDeclaration>,
        sample_rate: i64,
    ) -> Result<Option<PreparedControlFade<'a>>, Error> {
        let Definition::Control {
            start,
            end,
            shape,
            control,
            scope,
            smoothing_seconds,
        } = &self.0
        else {
            return Ok(None);
        };
        let declaration = controls
            .get(control)
            .ok_or_else(|| invalid(format!("Unknown crossfade control: {}", control.as_str())))?;
        declaration.validate_value(*start)?;
        declaration.validate_value(*end)?;
        let seconds = quantity::exact(&smoothing_seconds.to_string(), "seconds")?;
        let smoothing_frames = duration_frames(seconds, sample_rate)?;
        Ok(Some(PreparedControlFade {
            control,
            scope: *scope,
            default: declaration.default_value(),
            minimum: if declaration.polarity() == Polarity::Bipolar {
                -1.0
            } else {
                0.0
            },
            smoothing_frames,
            interval: (*start, *end),
            shape: (shape.inward(), shape.equal_power()),
        }))
    }

    pub fn control_weight(&self, value: f64) -> Result<f64, Error> {
        let (start, end, inward, equal_power) = self
            .control_route()
            .ok_or_else(|| invalid("Expected a control crossfade"))?;
        Ok(weight_at_position(
            (quantity::finite(value)? - start) / (end - start),
            inward,
            equal_power,
        ))
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PreparedControlFade<'a> {
    pub control: &'a Identifier,
    pub scope: ControlScope,
    pub default: f64,
    pub minimum: f64,
    pub smoothing_frames: Rational,
    pub interval: (f64, f64),
    pub shape: (bool, bool),
}

/// Evaluate a normalized crossfade position with exact endpoint gains.
/// The caller supplies a finite position.
pub fn weight_at_position(position: f64, inward: bool, equal_power: bool) -> f64 {
    let position = position.clamp(0.0, 1.0);
    if equal_power && position > 0.0 && position < 1.0 {
        let angle = PI * position / 2.0;
        if inward { angle.sin() } else { angle.cos() }
    } else if inward {
        position
    } else {
        1.0 - position
    }
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(tag = "input", rename_all = "snake_case", deny_unknown_fields)]
enum Definition {
    Key {
        start: i64,
        end: i64,
        #[serde(flatten)]
        shape: Shape,
    },
    Velocity {
        start: f64,
        end: f64,
        #[serde(flatten)]
        shape: Shape,
    },
    Control {
        start: f64,
        end: f64,
        #[serde(flatten)]
        shape: Shape,
        control: Identifier,
        #[serde(default)]
        scope: ControlScope,
        #[serde(default = "smoothing_default", deserialize_with = "seconds")]
        smoothing_seconds: f64,
    },
}

impl TryFrom<Definition> for Crossfade {
    type Error = Error;

    fn try_from(value: Definition) -> Result<Self, Error> {
        let valid = match &value {
            Definition::Key { start, end, .. } => start < end,
            Definition::Velocity { start, end, .. } => bounded_interval(*start, *end, 0.0),
            Definition::Control {
                start,
                end,
                smoothing_seconds,
                ..
            } => {
                if *smoothing_seconds < 0.0 {
                    return Err(invalid("crossfade smoothing must be nonnegative"));
                }
                bounded_interval(*start, *end, -1.0)
            }
        };
        if !valid {
            return Err(invalid(
                "Crossfade start must precede end within the input domain",
            ));
        }
        Ok(Self(value))
    }
}

impl From<Crossfade> for Definition {
    fn from(value: Crossfade) -> Self {
        value.0
    }
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
struct Shape {
    direction: Direction,
    #[serde(default)]
    curve: Curve,
}

impl Shape {
    fn inward(&self) -> bool {
        self.direction == Direction::In
    }

    fn equal_power(&self) -> bool {
        self.curve == Curve::EqualPower
    }

    fn weight(&self, position: f64) -> f64 {
        weight_at_position(position, self.inward(), self.equal_power())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum Direction {
    In,
    Out,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum Curve {
    #[default]
    Linear,
    EqualPower,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ControlScope {
    Instrument,
    #[default]
    Part,
    Trigger,
}

fn bounded_interval(start: f64, end: f64, minimum: f64) -> bool {
    minimum <= start && start < end && end <= 1.0
}

fn smoothing_default() -> f64 {
    0.005
}

fn seconds<'de, D: Deserializer<'de>>(d: D) -> Result<f64, D::Error> {
    quantity::deserialize_scalar(d, "seconds")
}

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
