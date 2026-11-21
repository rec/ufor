//! Portable phase-modulation graphs and their authored target facts.
use crate::control::Polarity;
use crate::envelfo::wire::RootWire;
use crate::envelfo::{self, Body, Generator, PreparationLimits, Waveform};
use crate::error::Error;
use crate::identifier::Identifier;
use crate::modulation::{Target, Unit};
use crate::quantity;
use crate::samples::processing::{ResolvedTarget, TargetMinimum};
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

/// A checked authored graph. Indices in its evaluation order refer to the
/// operator declaration order. Delayed edges place no ordering constraint.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Fm {
    operators: Vec<Operator>,
    edges: Vec<Edge>,
    carrier: Identifier,
    carrier_level: f64,
    #[serde(skip)]
    order: Vec<usize>,
}

impl Fm {
    pub fn operators(&self) -> &[Operator] {
        &self.operators
    }
    pub fn edges(&self) -> &[Edge] {
        &self.edges
    }
    pub fn carrier(&self) -> &Identifier {
        &self.carrier
    }
    pub fn carrier_level(&self) -> f64 {
        self.carrier_level
    }
    pub fn order(&self) -> &[usize] {
        &self.order
    }

    /// Resolve FM-owned addresses from the actual operator and edge declarations.
    /// Unknown addresses may be handled by the caller's shared SoundSettings.
    pub fn resolve_target(&self, target: &Target) -> Option<ResolvedTarget> {
        let name = target.name().as_str();
        let field = target.parameter().as_str();
        let (unit, default_value, minimum) = if (name, field) == ("fm", "carrier_level") {
            (Unit::Ratio, self.carrier_level, TargetMinimum::Nonnegative)
        } else if let Some(name) = name.strip_prefix("operator-") {
            let operator = self.operators.iter().find(|o| o.name.as_str() == name)?;
            match field {
                "ratio" => (Unit::Ratio, operator.ratio, TargetMinimum::Positive),
                "tuning_cents" => (
                    Unit::Cents,
                    operator.tuning_cents,
                    TargetMinimum::Unrestricted,
                ),
                _ => return None,
            }
        } else if let Some(name) = name.strip_prefix("edge-").filter(|_| field == "index") {
            let edge = self.edges.iter().find(|edge| edge.target_name() == name)?;
            (Unit::Radians, edge.index, TargetMinimum::Nonnegative)
        } else {
            return None;
        };
        Some(ResolvedTarget {
            unit,
            default_value,
            duration: None,
            scope: None,
            minimum,
        })
    }

    pub(crate) fn decode<'de, D: Deserializer<'de>>(
        d: D,
        limits: PreparationLimits,
    ) -> Result<Self, D::Error> {
        let wire = Definition::deserialize(d)?;
        wire.prepare(limits).map_err(serde::de::Error::custom)
    }
}

impl<'de> Deserialize<'de> for Fm {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        Self::decode(d, PreparationLimits::default())
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Operator {
    name: Identifier,
    ratio: f64,
    tuning_cents: f64,
    phase_cycles: f64,
    waveform: Waveform,
    envelope: Generator,
}

impl Operator {
    pub fn name(&self) -> &Identifier {
        &self.name
    }
    pub fn ratio(&self) -> f64 {
        self.ratio
    }
    pub fn tuning_cents(&self) -> f64 {
        self.tuning_cents
    }
    pub fn phase_cycles(&self) -> f64 {
        self.phase_cycles
    }
    pub fn waveform(&self) -> Waveform {
        self.waveform
    }
    pub fn envelope(&self) -> &Generator {
        &self.envelope
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Edge {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    name: Option<Identifier>,
    source: Identifier,
    destination: Identifier,
    #[serde(default)]
    index: f64,
    #[serde(default)]
    delayed: bool,
}

impl Edge {
    pub fn name(&self) -> Option<&Identifier> {
        self.name.as_ref()
    }
    pub fn source(&self) -> &Identifier {
        &self.source
    }
    pub fn destination(&self) -> &Identifier {
        &self.destination
    }
    pub fn index(&self) -> f64 {
        self.index
    }
    pub fn delayed(&self) -> bool {
        self.delayed
    }
    pub fn target_name(&self) -> String {
        self.name.as_ref().map_or_else(
            || format!("{}-{}", self.source.as_str(), self.destination.as_str()),
            |name| name.as_str().to_owned(),
        )
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Definition {
    operators: Vec<OperatorDefinition>,
    #[serde(default)]
    edges: Vec<Edge>,
    carrier: Identifier,
    #[serde(default = "one")]
    carrier_level: f64,
}

impl Definition {
    fn prepare(self, limits: PreparationLimits) -> Result<Fm, Error> {
        if !(2..=6).contains(&self.operators.len()) {
            return Err(invalid("FM requires two to six operators"));
        }
        envelfo::preparation_records(
            &serde_json::to_value(&self).map_err(|error| invalid(&error.to_string()))?,
            limits,
        )?;
        nonnegative(self.carrier_level)?;
        let operators = self
            .operators
            .into_iter()
            .map(OperatorDefinition::prepare)
            .collect::<Result<Vec<_>, _>>()?;
        let names: BTreeMap<_, _> = operators
            .iter()
            .enumerate()
            .map(|(i, o)| (&o.name, i))
            .collect();
        if names.len() != operators.len() {
            return Err(invalid("duplicate FM operator name"));
        }
        if !names.contains_key(&self.carrier) {
            return Err(invalid("FM carrier must name an operator"));
        }
        let mut edge_names = BTreeSet::new();
        let mut pending = vec![0; operators.len()];
        let mut successors = vec![Vec::new(); operators.len()];
        for edge in &self.edges {
            nonnegative(edge.index)?;
            let (Some(&source), Some(&destination)) =
                (names.get(&edge.source), names.get(&edge.destination))
            else {
                return Err(invalid("FM edge endpoint must name an operator"));
            };
            if !edge_names.insert(edge.target_name()) {
                return Err(invalid("duplicate FM edge target"));
            }
            if !edge.delayed {
                pending[destination] += 1;
                successors[source].push(destination);
            }
        }
        let mut ready: Vec<_> = (0..pending.len()).filter(|&i| pending[i] == 0).collect();
        let mut order = Vec::with_capacity(pending.len());
        while let Some(operator) = ready.pop() {
            order.push(operator);
            for &destination in &successors[operator] {
                pending[destination] -= 1;
                if pending[destination] == 0 {
                    ready.push(destination);
                }
            }
        }
        if order.len() != operators.len() {
            return Err(invalid("current-sample FM edges must be acyclic"));
        }
        Ok(Fm {
            operators,
            edges: self.edges,
            carrier: self.carrier,
            carrier_level: self.carrier_level,
            order,
        })
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct OperatorDefinition {
    name: Identifier,
    #[serde(default = "one")]
    ratio: f64,
    #[serde(default)]
    tuning_cents: Scalar,
    #[serde(default)]
    phase_cycles: Scalar,
    #[serde(default)]
    waveform: Waveform,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present_envelope"
    )]
    envelope: Option<Value>,
}

impl OperatorDefinition {
    fn prepare(self) -> Result<Operator, Error> {
        if quantity::finite(self.ratio)? <= 0.0 {
            return Err(invalid("FM operator ratio must be positive"));
        }
        let phase_cycles = self.phase_cycles.value("phase")?;
        if !(0.0..1.0).contains(&phase_cycles) {
            return Err(invalid("FM operator phase must be in [0, 1)"));
        }
        let envelope = RootWire::envelope(self.envelope.unwrap_or_else(|| {
            json!({
                "segments": [{"duration": 0, "to": 1}],
                "release": [{"duration": 0, "to": 0}],
            })
        }))?;
        if !matches!(envelope.body(), Body::Envelope(body) if body.polarity() == Polarity::Unipolar)
        {
            return Err(invalid("FM operator amplitude Envelopes must be unipolar"));
        }
        Ok(Operator {
            name: self.name,
            ratio: self.ratio,
            tuning_cents: self.tuning_cents.value("cents")?,
            phase_cycles,
            waveform: self.waveform,
            envelope,
        })
    }
}

#[derive(Serialize, Deserialize)]
#[serde(untagged)]
enum Scalar {
    Number(f64),
    Text(String),
}
impl Default for Scalar {
    fn default() -> Self {
        Self::Number(0.0)
    }
}
impl Scalar {
    fn value(self, unit: &str) -> Result<f64, Error> {
        match self {
            Self::Number(value) => quantity::finite(value),
            Self::Text(text) if unit == "phase" => {
                let value = quantity::exact(&text, unit)?;
                Ok(value.numerator() as f64 / value.denominator() as f64)
            }
            Self::Text(text) => quantity::scalar(&text, unit),
        }
    }
}

fn present_envelope<'de, D: Deserializer<'de>>(d: D) -> Result<Option<Value>, D::Error> {
    Value::deserialize(d).map(Some)
}

fn one() -> f64 {
    1.0
}
fn nonnegative(value: f64) -> Result<(), Error> {
    if quantity::finite(value)? < 0.0 {
        Err(invalid("FM index and carrier level must be nonnegative"))
    } else {
        Ok(())
    }
}
fn invalid(message: &str) -> Error {
    Error::Invalid(message.into())
}
