//! Named controller domains without a smoothing runtime.
use crate::control::Polarity;
use crate::error::Error;
use crate::quantity::finite;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "Definition", into = "Definition")]
pub struct ControlDeclaration {
    polarity: Polarity,
    default: f64,
}
impl ControlDeclaration {
    pub fn new(polarity: Polarity, default: f64) -> Result<Self, Error> {
        let value = Self { polarity, default };
        value.validate_value(default)?;
        Ok(value)
    }
    pub fn polarity(&self) -> Polarity {
        self.polarity
    }
    pub fn default_value(&self) -> f64 {
        self.default
    }
    pub fn validate_value(&self, value: f64) -> Result<(), Error> {
        finite(value)?;
        let minimum = if self.polarity == Polarity::Bipolar {
            -1.0
        } else {
            0.0
        };
        if !(minimum..=1.0).contains(&value) {
            return Err(Error::Invalid(
                "control value outside polarity domain".into(),
            ));
        }
        Ok(())
    }
}
impl Default for ControlDeclaration {
    fn default() -> Self {
        Self {
            polarity: Polarity::Unipolar,
            default: 0.0,
        }
    }
}
#[derive(Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
struct Definition {
    polarity: Polarity,
    default: f64,
}
impl TryFrom<Definition> for ControlDeclaration {
    type Error = Error;
    fn try_from(v: Definition) -> Result<Self, Error> {
        Self::new(v.polarity, v.default)
    }
}
impl From<ControlDeclaration> for Definition {
    fn from(v: ControlDeclaration) -> Self {
        Self {
            polarity: v.polarity,
            default: v.default,
        }
    }
}
