//! Scalar timeline curves on a score's native clock.

pub mod placement;

use crate::control::Scope;
use crate::envelfo::PreparationLimits;
use crate::error::Error;
use crate::identifier::Identifier;
use crate::modulation::math::{add_partial, sum_partials};
use crate::modulation::{Operation, Target, Unit};
use crate::musical::header;
use crate::number::round_binary_ratio;
use crate::quantity;
use crate::time::Timebase;
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Quantity {
    Gain,
    Frequency,
    Gate,
}

impl Quantity {
    fn unit(self) -> Unit {
        match self {
            Self::Gain => Unit::Ratio,
            Self::Frequency => Unit::Hz,
            Self::Gate => Unit::Logical,
        }
    }

    fn check(self, value: Value) -> Result<(), Error> {
        match (self, value) {
            (Self::Gate, Value::Gate(_)) => Ok(()),
            (Self::Gain, Value::Number(value)) if value.is_finite() && value >= 0.0 => Ok(()),
            (Self::Frequency, Value::Number(value)) if value.is_finite() && value > 0.0 => Ok(()),
            _ => Err(invalid("value is outside the automation quantity's domain")),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize, Serialize)]
#[serde(untagged)]
pub enum Value {
    Number(f64),
    Gate(bool),
}

impl Value {
    fn number(self) -> Result<f64, Error> {
        match self {
            Self::Number(value) => quantity::finite(value),
            Self::Gate(_) => Err(invalid("automation arithmetic requires numbers")),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(untagged)]
pub enum AutomationTarget {
    Parameter(Target),
    Arrangement(ArrangementGainTarget),
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum ArrangementGainTarget {
    Clip {
        name: Identifier,
    },
    Bus {
        name: Identifier,
    },
    Route {
        name: Identifier,
        destination: Identifier,
    },
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(try_from = "Definition")]
pub struct Automation {
    target: AutomationTarget,
    scope: Scope,
    quantity: Quantity,
    unit: Unit,
    default: Value,
    curves: Vec<Curve>,
    #[serde(skip)]
    evaluation_order: Vec<usize>,
}

impl Automation {
    pub fn target(&self) -> &AutomationTarget {
        &self.target
    }

    pub fn scope(&self) -> Scope {
        self.scope
    }

    pub fn quantity(&self) -> Quantity {
        self.quantity
    }

    pub fn unit(&self) -> Unit {
        self.unit
    }

    /// Evaluate at a native tick. An override replaces the base before any
    /// direct curve starts. Arithmetic contributions combine in name order.
    pub fn evaluate(&self, tick: i64, base_override: Option<Value>) -> Result<Value, Error> {
        let mut base = base_override.unwrap_or(self.default);
        self.quantity.check(base)?;
        let mut partials = Vec::new();
        let mut count = 0;
        let mut product = 1.0;
        for &index in &self.evaluation_order {
            let curve = &self.curves[index];
            if tick < curve.at {
                continue;
            }
            let value = curve.value(tick);
            match curve.operation {
                None => base = value,
                Some(Operation::Add) => {
                    if count == partials.len() {
                        partials.push(0.0);
                    }
                    add_partial(&mut partials, &mut count, value.number()?)
                        .map_err(|_| Error::ArithmeticRange)?;
                }
                Some(Operation::Multiply) => product *= value.number()?,
            }
        }
        if self.quantity == Quantity::Gate {
            return Ok(base);
        }
        let additions = sum_partials(&partials[..count]).map_err(|_| Error::ArithmeticRange)?;
        let result = Value::Number((base.number()? + additions) * product);
        self.quantity.check(result)?;
        Ok(result)
    }

    pub(crate) fn check_records(
        &self,
        limits: PreparationLimits,
        overhead: usize,
    ) -> Result<(), Error> {
        let count = overhead
            + 1
            + self
                .curves
                .iter()
                .map(|curve| 1 + curve.segments.len())
                .sum::<usize>();
        if count > limits.max_records() {
            return Err(Error::Limit("automation records"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(try_from = "ScoreDefinition", into = "ScoreDefinition")]
pub struct AutomationScore {
    name: String,
    title: String,
    tags: Vec<String>,
    timebase: Timebase,
    output: ControlOutput,
    body: Automation,
}

impl AutomationScore {
    pub fn name(&self) -> &str {
        &self.name
    }

    pub fn title(&self) -> &str {
        &self.title
    }

    pub fn tags(&self) -> &[String] {
        &self.tags
    }

    pub fn timebase(&self) -> &Timebase {
        &self.timebase
    }

    pub fn output(&self) -> &ControlOutput {
        &self.output
    }

    pub fn body(&self) -> &Automation {
        &self.body
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ControlOutput {
    pub name: Identifier,
    pub stream: ControlStream,
    binding: ControlBinding,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ControlStream {
    #[serde(default)]
    family: ControlFamily,
    pub timebase: Identifier,
    pub quantity: Quantity,
    pub unit: Unit,
    pub scope: Scope,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum Interpolation {
    Hold,
    #[default]
    Linear,
    EqualPower,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
struct Segment {
    duration: i64,
    to: Value,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
struct Curve {
    name: Identifier,
    unit: Unit,
    interpolation: Interpolation,
    at: i64,
    initial: Value,
    segments: Vec<Segment>,
    #[serde(skip_serializing_if = "Option::is_none")]
    operation: Option<Operation>,
}

impl Curve {
    fn value(&self, tick: i64) -> Value {
        let mut elapsed = tick.abs_diff(self.at);
        let mut value = self.initial;
        for segment in &self.segments {
            // Durations are validated nonnegative. Subtracting elapsed ticks
            // avoids overflow when the curve extends beyond signed ticks.
            let duration = segment.duration as u64;
            if elapsed >= duration {
                elapsed -= duration;
                value = segment.to;
                continue;
            }
            if self.interpolation == Interpolation::Hold {
                return value;
            }
            let (Value::Number(start), Value::Number(end)) = (value, segment.to) else {
                unreachable!("interpolated values are numeric");
            };
            let progress = round_binary_ratio(u128::from(elapsed), u128::from(duration), 0);
            return Value::Number(match self.interpolation {
                Interpolation::Linear => (1.0 - progress) * start + progress * end,
                Interpolation::EqualPower => {
                    ((1.0 - progress) * (start * start) + progress * (end * end)).sqrt()
                }
                Interpolation::Hold => unreachable!(),
            });
        }
        value
    }
}

#[derive(Deserialize)]
#[serde(untagged)]
enum ValueDefinition {
    Scalar(Value),
    Text(String),
}

impl ValueDefinition {
    fn resolve(self, unit: Unit) -> Result<Value, Error> {
        match self {
            Self::Scalar(value) => Ok(value),
            Self::Text(text) => quantity::scalar(&text, unit.as_str()).map(Value::Number),
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SegmentDefinition {
    duration: i64,
    to: ValueDefinition,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CurveDefinition {
    name: Identifier,
    unit: Unit,
    #[serde(default)]
    interpolation: Interpolation,
    at: i64,
    initial: ValueDefinition,
    #[serde(default)]
    segments: Vec<SegmentDefinition>,
    operation: Option<Operation>,
}

impl CurveDefinition {
    fn prepare(self, quantity: Quantity) -> Result<Curve, Error> {
        let required = if self.operation == Some(Operation::Multiply) {
            Unit::Ratio
        } else {
            quantity.unit()
        };
        if self.unit != required {
            return Err(invalid(
                "automation curve unit does not match its operation",
            ));
        }
        if quantity == Quantity::Gate
            && (self.operation.is_some() || self.interpolation != Interpolation::Hold)
        {
            return Err(invalid("gates require direct hold curves"));
        }
        if self.interpolation == Interpolation::EqualPower
            && (quantity != Quantity::Gain || self.operation.is_some())
        {
            return Err(invalid(
                "equal-power interpolation requires a direct gain curve",
            ));
        }
        let resolve = |value: ValueDefinition| {
            let value = value.resolve(self.unit)?;
            if self.operation.is_none() {
                quantity.check(value)?;
            } else {
                value.number()?;
            }
            Ok(value)
        };
        let initial = resolve(self.initial)?;
        let segments = self
            .segments
            .into_iter()
            .map(|segment| {
                if segment.duration < 0 {
                    return Err(invalid("automation duration must be nonnegative"));
                }
                Ok(Segment {
                    duration: segment.duration,
                    to: resolve(segment.to)?,
                })
            })
            .collect::<Result<_, Error>>()?;
        Ok(Curve {
            name: self.name,
            unit: self.unit,
            interpolation: self.interpolation,
            at: self.at,
            initial,
            segments,
            operation: self.operation,
        })
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Definition {
    target: AutomationTarget,
    scope: Scope,
    quantity: Quantity,
    unit: Unit,
    default: ValueDefinition,
    #[serde(default)]
    curves: Vec<CurveDefinition>,
}

impl TryFrom<Definition> for Automation {
    type Error = Error;

    fn try_from(value: Definition) -> Result<Self, Error> {
        if value.unit != value.quantity.unit() {
            return Err(invalid("automation unit does not match its quantity"));
        }
        if matches!(value.target, AutomationTarget::Arrangement(_))
            && value.quantity != Quantity::Gain
        {
            return Err(invalid("arrangement targets support gain only"));
        }
        let default = value.default.resolve(value.unit)?;
        value.quantity.check(default)?;
        let curves = value
            .curves
            .into_iter()
            .map(|curve| curve.prepare(value.quantity))
            .collect::<Result<Vec<_>, _>>()?;
        if curves
            .iter()
            .filter(|curve| curve.operation.is_none())
            .count()
            > 1
        {
            return Err(invalid("automation has competing direct writers"));
        }
        let mut evaluation_order: Vec<_> = (0..curves.len()).collect();
        evaluation_order.sort_unstable_by_key(|&index| &curves[index].name);
        if evaluation_order
            .windows(2)
            .any(|pair| curves[pair[0]].name == curves[pair[1]].name)
        {
            return Err(invalid("duplicate automation curve name"));
        }
        Ok(Self {
            target: value.target,
            scope: value.scope,
            quantity: value.quantity,
            unit: value.unit,
            default,
            curves,
            evaluation_order,
        })
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum ControlFamily {
    #[default]
    Control,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ControlBinding {
    #[serde(default = "yes")]
    control: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ScoreDefinition {
    #[serde(default = "format")]
    format: String,
    #[serde(default = "version")]
    version: i64,
    #[serde(default = "kind")]
    kind: String,
    name: String,
    title: String,
    #[serde(default)]
    tags: Vec<String>,
    timebases: [Timebase; 1],
    outputs: [ControlOutput; 1],
    #[serde(default)]
    inputs: Vec<serde_json::Value>,
    #[serde(default)]
    parameters: Vec<serde_json::Value>,
    body: Automation,
}

impl TryFrom<ScoreDefinition> for AutomationScore {
    type Error = Error;

    fn try_from(value: ScoreDefinition) -> Result<Self, Error> {
        if value.format != "recs" || value.version != 4 || value.kind != "automation" {
            return Err(invalid("expected a recs version 4 automation score"));
        }
        if !value.inputs.is_empty() || !value.parameters.is_empty() {
            return Err(invalid("automation scores have no inputs or parameters"));
        }
        let [timebase] = value.timebases;
        let [output] = value.outputs;
        if !output.binding.control
            || &output.stream.timebase != timebase.name()
            || output.stream.quantity != value.body.quantity
            || output.stream.unit != value.body.unit
            || output.stream.scope != value.body.scope
        {
            return Err(invalid("automation output must match its curve contract"));
        }
        let tags = header(&value.name, &value.title, value.tags)?;
        Ok(Self {
            name: value.name,
            title: value.title,
            tags,
            timebase,
            output,
            body: value.body,
        })
    }
}

impl From<AutomationScore> for ScoreDefinition {
    fn from(value: AutomationScore) -> Self {
        Self {
            format: format(),
            version: version(),
            kind: kind(),
            name: value.name,
            title: value.title,
            tags: value.tags,
            timebases: [value.timebase],
            outputs: [value.output],
            inputs: Vec::new(),
            parameters: Vec::new(),
            body: value.body,
        }
    }
}

fn format() -> String {
    "recs".into()
}

fn version() -> i64 {
    4
}

fn kind() -> String {
    "automation".into()
}

fn yes() -> bool {
    true
}

fn invalid(message: &str) -> Error {
    Error::Invalid(message.into())
}
