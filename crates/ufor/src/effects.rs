//! Portable effect processors and their modulation targets.
use crate::error::Error;
use crate::identifier::Identifier;
use crate::modulation::{Parameter, Unit};
use crate::quantity;
use crate::samples::processing::ResonantFilter;
use serde::{Deserialize, Deserializer, Serialize};
use std::collections::BTreeSet;

/// A checked declaration for the supported effect processor families.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "Definition", into = "Definition")]
pub struct Processor(Definition);

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct TargetFacts {
    pub unit: Unit,
    pub default_value: f64,
    domain: Domain,
}

impl Processor {
    pub fn name(&self) -> &Identifier {
        match &self.0 {
            Definition::Gain { name, .. }
            | Definition::Multiply { name, .. }
            | Definition::FrequencyShifter { name, .. }
            | Definition::Filter { name, .. } => name,
        }
    }

    pub fn resolve_target(&self, field: &str) -> Option<TargetFacts> {
        let (unit, default_value, domain) = match &self.0 {
            Definition::Gain { gain_db, .. } if field == "gain_db" => {
                (Unit::Db, *gain_db, Domain::Finite)
            }
            Definition::FrequencyShifter { shift_hz, .. } if field == "shift_hz" => {
                (Unit::HzOffset, *shift_hz, Domain::Closed(-2000.0, 2000.0))
            }
            Definition::Gain { mix, .. }
            | Definition::Multiply { mix, .. }
            | Definition::FrequencyShifter { mix, .. }
            | Definition::Filter { mix, .. }
                if field == "mix" =>
            {
                (Unit::Ratio, *mix, Domain::Closed(0.0, 1.0))
            }
            Definition::Filter { filters, .. } => {
                let (name, field) = field.rsplit_once('-')?;
                let filter = filters.iter().find(|f| f.name().as_str() == name)?;
                match field {
                    "cutoff_hz" => (Unit::Hz, filter.cutoff_hz(), Domain::Positive),
                    "q" => (Unit::Ratio, filter.q(), Domain::Positive),
                    _ => return None,
                }
            }
            _ => return None,
        };
        Some(TargetFacts {
            unit,
            default_value,
            domain,
        })
    }

    pub fn validate_parameter(&self, parameter: &Parameter) -> Result<(), Error> {
        let target = parameter.target();
        let facts = (target.name() == self.name())
            .then(|| self.resolve_target(target.parameter().as_str()))
            .flatten()
            .ok_or_else(|| Error::Invalid("unknown effect modulation target".into()))?;
        if parameter.unit() != facts.unit || parameter.default_value() != facts.default_value {
            return Err(Error::Invalid(
                "effect parameter unit and default must match the processor".into(),
            ));
        }
        facts.domain.check(parameter.minimum())?;
        facts.domain.check(parameter.maximum())
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum Domain {
    Finite,
    Positive,
    Closed(f64, f64),
}

impl Domain {
    fn check(self, value: f64) -> Result<(), Error> {
        quantity::finite(value)?;
        let valid = match self {
            Self::Finite => true,
            Self::Positive => value > 0.0,
            Self::Closed(minimum, maximum) => (minimum..=maximum).contains(&value),
        };
        if valid {
            Ok(())
        } else {
            Err(Error::Invalid(
                "effect parameter is outside its domain".into(),
            ))
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Definition {
    Gain {
        name: Identifier,
        #[serde(default, deserialize_with = "decibels")]
        gain_db: f64,
        #[serde(default = "one")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
    },
    Multiply {
        name: Identifier,
        #[serde(default = "one")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
    },
    FrequencyShifter {
        name: Identifier,
        #[serde(default, deserialize_with = "hertz")]
        shift_hz: f64,
        #[serde(default = "one")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
    },
    Filter {
        name: Identifier,
        filters: Vec<ResonantFilter>,
        #[serde(default = "one")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
        #[serde(default = "threshold")]
        tail_threshold: f64,
        #[serde(default = "floor")]
        state_floor: f64,
    },
}

impl TryFrom<Definition> for Processor {
    type Error = Error;

    fn try_from(value: Definition) -> Result<Self, Error> {
        let (mix, frames) = match &value {
            Definition::Gain {
                mix,
                bypass_fade_frames,
                ..
            }
            | Definition::Multiply {
                mix,
                bypass_fade_frames,
                ..
            }
            | Definition::FrequencyShifter {
                mix,
                bypass_fade_frames,
                ..
            }
            | Definition::Filter {
                mix,
                bypass_fade_frames,
                ..
            } => (*mix, *bypass_fade_frames),
        };
        Domain::Closed(0.0, 1.0).check(mix)?;
        if frames < 1 {
            return Err(Error::Invalid(
                "effect bypass fade requires positive frames".into(),
            ));
        }
        match &value {
            Definition::Gain { gain_db, .. } => Domain::Finite.check(*gain_db)?,
            Definition::FrequencyShifter { shift_hz, .. } => {
                Domain::Closed(-2000.0, 2000.0).check(*shift_hz)?
            }
            Definition::Filter {
                filters,
                tail_threshold,
                state_floor,
                ..
            } => {
                Domain::Positive.check(*tail_threshold)?;
                Domain::Positive.check(*state_floor)?;
                if state_floor >= tail_threshold {
                    return Err(Error::Invalid(
                        "filter state_floor must be below tail_threshold".into(),
                    ));
                }
                if filters.is_empty()
                    || filters
                        .iter()
                        .map(ResonantFilter::name)
                        .collect::<BTreeSet<_>>()
                        .len()
                        != filters.len()
                {
                    return Err(Error::Invalid(
                        "effect filter requires unique named stages".into(),
                    ));
                }
            }
            Definition::Multiply { .. } => (),
        }
        Ok(Self(value))
    }
}

impl From<Processor> for Definition {
    fn from(value: Processor) -> Self {
        value.0
    }
}

fn decibels<'de, D: Deserializer<'de>>(d: D) -> Result<f64, D::Error> {
    quantity::deserialize_scalar(d, "db")
}
fn hertz<'de, D: Deserializer<'de>>(d: D) -> Result<f64, D::Error> {
    quantity::deserialize_scalar(d, "hz")
}
fn one() -> f64 {
    1.0
}
fn fade() -> i64 {
    64
}
fn threshold() -> f64 {
    1e-12
}
fn floor() -> f64 {
    1e-30
}
