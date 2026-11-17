//! Typed scalar routes and their stateless reference mathematics.
#![doc = include_str!("../../../doc/rust-modulation.md")]
pub mod math;
use crate::control::Scope;
use crate::error::Error;
use crate::identifier::Identifier;
use crate::quantity::{self, finite, records};
use serde::{Deserialize, Deserializer, Serialize};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Unit {
    Logical,
    Ratio,
    Db,
    Cents,
    Hz,
    #[serde(rename = "hz_offset")]
    HzOffset,
    Normalized,
    Volts,
    Seconds,
    Beats,
    Radians,
}
impl Unit {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Logical => "logical",
            Self::Ratio => "ratio",
            Self::Db => "db",
            Self::Cents => "cents",
            Self::Hz => "hz",
            Self::HzOffset => "hz_offset",
            Self::Normalized => "normalized",
            Self::Volts => "volts",
            Self::Seconds => "seconds",
            Self::Beats => "beats",
            Self::Radians => "radians",
        }
    }
}
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Operation {
    Add,
    Multiply,
}
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Interpolation {
    #[default]
    Linear,
    Step,
    Exponential,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SourceScope {
    Voice,
    Instrument,
    Part,
    Trigger,
}

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Target {
    name: Identifier,
    parameter: Identifier,
}
impl Target {
    pub fn new(name: Identifier, parameter: Identifier) -> Self {
        Self { name, parameter }
    }
    pub fn name(&self) -> &Identifier {
        &self.name
    }
    pub fn parameter(&self) -> &Identifier {
        &self.parameter
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "ParameterDefinition", into = "ParameterDefinition")]
pub struct Parameter {
    target: Target,
    unit: Unit,
    scope: Scope,
    minimum: f64,
    maximum: f64,
    default: f64,
}
impl Parameter {
    pub fn new(
        target: Target,
        unit: Unit,
        scope: Scope,
        minimum: f64,
        maximum: f64,
        default: f64,
    ) -> Result<Self, Error> {
        for value in [minimum, maximum, default] {
            finite(value)?;
        }
        if minimum > default
            || default > maximum
            || (unit == Unit::Hz && minimum <= 0.0)
            || (matches!(unit, Unit::Seconds | Unit::Beats) && minimum < 0.0)
            || (unit == Unit::Normalized && (minimum < -1.0 || maximum > 1.0))
        {
            return Err(invalid("invalid parameter domain or default"));
        }
        Ok(Self {
            target,
            unit,
            scope,
            minimum,
            maximum,
            default,
        })
    }
    pub fn target(&self) -> &Target {
        &self.target
    }
    pub fn unit(&self) -> Unit {
        self.unit
    }
    pub fn scope(&self) -> Scope {
        self.scope
    }
    pub fn minimum(&self) -> f64 {
        self.minimum
    }
    pub fn maximum(&self) -> f64 {
        self.maximum
    }
    pub fn default_value(&self) -> f64 {
        self.default
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "SourceDefinition", into = "SourceDefinition")]
pub struct Source {
    name: Identifier,
    scope: SourceScope,
    minimum: f64,
    maximum: f64,
}
impl Source {
    pub fn new(
        name: Identifier,
        scope: SourceScope,
        minimum: f64,
        maximum: f64,
    ) -> Result<Self, Error> {
        finite(minimum)?;
        finite(maximum)?;
        if maximum < minimum {
            return Err(invalid("source maximum precedes minimum"));
        }
        Ok(Self {
            name,
            scope,
            minimum,
            maximum,
        })
    }
    pub fn name(&self) -> &Identifier {
        &self.name
    }
    pub fn scope(&self) -> SourceScope {
        self.scope
    }
    pub fn minimum(&self) -> f64 {
        self.minimum
    }
    pub fn maximum(&self) -> f64 {
        self.maximum
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "PointDefinition", into = "PointDefinition")]
pub struct Point {
    input: f64,
    amount: f64,
}
impl Point {
    pub fn new(input: f64, amount: f64) -> Result<Self, Error> {
        Ok(Self {
            input: finite(input)?,
            amount: finite(amount)?,
        })
    }
    pub fn input(&self) -> f64 {
        self.input
    }
    pub fn amount(&self) -> f64 {
        self.amount
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "RouteDefinition", into = "RouteDefinition")]
pub struct Route {
    name: Identifier,
    source: Identifier,
    target: Target,
    operation: Operation,
    unit: Unit,
    points: Vec<Point>,
    interpolation: Interpolation,
}
impl Route {
    pub fn new(
        name: Identifier,
        source: Identifier,
        target: Target,
        operation: Operation,
        unit: Unit,
        points: Vec<Point>,
        interpolation: Interpolation,
    ) -> Result<Self, Error> {
        Self {
            name,
            source,
            target,
            operation,
            unit,
            points,
            interpolation,
        }
        .checked(quantity::MAX_RECORDS)
    }
    fn checked(self, maximum: usize) -> Result<Self, Error> {
        quantity::record_budget(
            self.points
                .len()
                .checked_add(1)
                .ok_or(Error::ArithmeticRange)?,
            maximum,
        )?;
        math::validate(self.interpolation, &self.points)?;
        Ok(self)
    }
    pub fn name(&self) -> &Identifier {
        &self.name
    }
    pub fn source(&self) -> &Identifier {
        &self.source
    }
    pub fn target(&self) -> &Target {
        &self.target
    }
    pub fn operation(&self) -> Operation {
        self.operation
    }
    pub fn unit(&self) -> Unit {
        self.unit
    }
    pub fn points(&self) -> &[Point] {
        &self.points
    }
    pub fn interpolation(&self) -> Interpolation {
        self.interpolation
    }
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "ModulationDefinition", into = "ModulationDefinition")]
pub struct Modulation {
    parameters: Vec<Parameter>,
    sources: Vec<Source>,
    routes: Vec<Route>,
}
impl Modulation {
    pub fn new(
        parameters: Vec<Parameter>,
        sources: Vec<Source>,
        routes: Vec<Route>,
    ) -> Result<Self, Error> {
        Self {
            parameters,
            sources,
            routes,
        }
        .checked(quantity::MAX_RECORDS)
    }
    pub fn decode<'de, D: Deserializer<'de>>(d: D, max_records: usize) -> Result<Self, D::Error> {
        ModulationDefinition::deserialize(d)?
            .prepare(max_records)
            .map_err(serde::de::Error::custom)
    }
    fn checked(self, maximum: usize) -> Result<Self, Error> {
        let Self {
            parameters,
            sources,
            routes,
        } = self;
        let mut count = 0_usize;
        for length in [parameters.len(), sources.len(), routes.len()] {
            count = count.checked_add(length).ok_or(Error::ArithmeticRange)?;
            quantity::record_budget(count, maximum)?;
        }
        for route in &routes {
            count = count
                .checked_add(route.points.len())
                .ok_or(Error::ArithmeticRange)?;
            quantity::record_budget(count, maximum)?;
        }
        let source_map: BTreeMap<_, _> = sources.iter().map(|s| (&s.name, s)).collect();
        let parameter_map: BTreeMap<_, _> = parameters.iter().map(|p| (&p.target, p)).collect();
        let route_names: BTreeSet<_> = routes.iter().map(|r| &r.name).collect();
        if source_map.len() != sources.len()
            || parameter_map.len() != parameters.len()
            || route_names.len() != routes.len()
        {
            return Err(invalid("duplicate source, route or parameter target"));
        }
        for route in &routes {
            let source = source_map
                .get(&route.source)
                .ok_or_else(|| invalid("unknown route source"))?;
            let parameter = parameter_map
                .get(&route.target)
                .ok_or_else(|| invalid("unknown route target"))?;
            let unit = if route.operation == Operation::Add {
                parameter.unit
            } else {
                Unit::Ratio
            };
            if route.unit != unit
                || (parameter.scope == Scope::Instrument && source.scope != SourceScope::Instrument)
                || route
                    .points
                    .iter()
                    .any(|p| p.input < source.minimum || p.input > source.maximum)
            {
                return Err(invalid("incompatible route unit, scope or source domain"));
            }
        }
        Ok(Self {
            parameters,
            sources,
            routes,
        })
    }
    pub fn parameters(&self) -> &[Parameter] {
        &self.parameters
    }
    pub fn sources(&self) -> &[Source] {
        &self.sources
    }
    pub fn routes(&self) -> &[Route] {
        &self.routes
    }
    pub fn record_count(&self) -> usize {
        self.parameters.len()
            + self.sources.len()
            + self
                .routes
                .iter()
                .map(|r| 1 + r.points.len())
                .sum::<usize>()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "SourceValueDefinition", into = "SourceValueDefinition")]
pub struct SourceValue {
    value: f64,
    weight: f64,
}
impl SourceValue {
    pub fn new(value: f64, weight: f64) -> Result<Self, Error> {
        finite(value)?;
        finite(weight)?;
        if !(0.0..=1.0).contains(&weight) {
            return Err(invalid("invalid source weight"));
        }
        Ok(Self { value, weight })
    }
    pub fn value(self) -> f64 {
        self.value
    }
    pub fn weight(self) -> f64 {
        self.weight
    }
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(
    try_from = "ParameterValueDefinition",
    into = "ParameterValueDefinition"
)]
pub struct ParameterValue {
    target: Target,
    value: f64,
}
impl ParameterValue {
    pub fn new(target: Target, value: f64) -> Result<Self, Error> {
        Ok(Self {
            target,
            value: finite(value)?,
        })
    }
    pub fn target(&self) -> &Target {
        &self.target
    }
    pub fn value(&self) -> f64 {
        self.value
    }
}

pub fn map_value(route: &Route, value: f64) -> Result<f64, Error> {
    math::map_points(route.interpolation, &route.points, value).map_err(|_| Error::ArithmeticRange)
}

pub fn evaluate(
    modulation: &Modulation,
    values: &BTreeMap<Identifier, SourceValue>,
    base_values: &[ParameterValue],
) -> Result<Vec<ParameterValue>, Error> {
    records(values.len())?;
    records(base_values.len())?;
    let sources: BTreeMap<_, _> = modulation.sources.iter().map(|s| (&s.name, s)).collect();
    for (name, value) in values {
        let source = sources
            .get(name)
            .ok_or_else(|| invalid("unknown supplied source"))?;
        if value.value < source.minimum || value.value > source.maximum {
            return Err(invalid("source value outside domain"));
        }
    }
    let parameters: BTreeSet<_> = modulation.parameters.iter().map(|p| &p.target).collect();
    let mut overrides = BTreeMap::new();
    for value in base_values {
        if !parameters.contains(&value.target)
            || overrides.insert(&value.target, value.value).is_some()
        {
            return Err(invalid("unknown or duplicate base value"));
        }
    }
    let mut routes: Vec<_> = modulation.routes.iter().collect();
    routes.sort_by_key(|r| (&r.source, &r.name));
    let mut contributions: BTreeMap<&Target, Vec<(Operation, f64)>> = BTreeMap::new();
    for route in routes {
        let source = values
            .get(&route.source)
            .ok_or_else(|| invalid("missing routed source"))?;
        let amount = map_value(route, source.value)?;
        let neutral = if route.operation == Operation::Add {
            0.0
        } else {
            1.0
        };
        let amount = finite(neutral + finite(source.weight * finite(amount - neutral)?)?)?;
        contributions
            .entry(&route.target)
            .or_default()
            .push((route.operation, amount));
    }
    let mut result = Vec::with_capacity(modulation.parameters.len());
    for parameter in &modulation.parameters {
        let base = overrides
            .get(&parameter.target)
            .copied()
            .unwrap_or(parameter.default);
        if base < parameter.minimum || base > parameter.maximum {
            return Err(invalid("base value outside domain"));
        }
        let terms = contributions
            .get(&parameter.target)
            .map(Vec::as_slice)
            .unwrap_or(&[]);
        let mut partials = vec![0.0; terms.len()];
        let mut count = 0;
        for (_, value) in terms.iter().filter(|(o, _)| *o == Operation::Add) {
            math::add_partial(&mut partials, &mut count, *value)
                .map_err(|_| Error::ArithmeticRange)?;
        }
        let sum = math::sum_partials(&partials[..count]).map_err(|_| Error::ArithmeticRange)?;
        let mut product = 1.0;
        for (_, value) in terms.iter().filter(|(o, _)| *o == Operation::Multiply) {
            product = finite(product * value)?;
        }
        let value = finite(finite(base + sum)? * product)?;
        if value < parameter.minimum || value > parameter.maximum {
            return Err(invalid("modulated value outside domain"));
        }
        result.push(ParameterValue::new(parameter.target.clone(), value)?);
    }
    Ok(result)
}

fn invalid(message: &str) -> Error {
    Error::Invalid(message.into())
}
fn weight() -> f64 {
    1.0
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(untagged)]
enum ScalarInput {
    Number(f64),
    Text(String),
}
impl ScalarInput {
    fn normalize(self, unit: Unit) -> Result<f64, Error> {
        match self {
            Self::Number(v) => finite(v),
            Self::Text(v) => quantity::scalar(&v, unit.as_str()),
        }
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ParameterDefinition {
    target: Target,
    unit: Unit,
    scope: Scope,
    minimum: ScalarInput,
    maximum: ScalarInput,
    default: ScalarInput,
}
impl TryFrom<ParameterDefinition> for Parameter {
    type Error = Error;
    fn try_from(v: ParameterDefinition) -> Result<Self, Error> {
        Self::new(
            v.target,
            v.unit,
            v.scope,
            v.minimum.normalize(v.unit)?,
            v.maximum.normalize(v.unit)?,
            v.default.normalize(v.unit)?,
        )
    }
}
impl From<Parameter> for ParameterDefinition {
    fn from(v: Parameter) -> Self {
        Self {
            target: v.target,
            unit: v.unit,
            scope: v.scope,
            minimum: ScalarInput::Number(v.minimum),
            maximum: ScalarInput::Number(v.maximum),
            default: ScalarInput::Number(v.default),
        }
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SourceDefinition {
    name: Identifier,
    scope: SourceScope,
    minimum: f64,
    maximum: f64,
}
impl TryFrom<SourceDefinition> for Source {
    type Error = Error;
    fn try_from(v: SourceDefinition) -> Result<Self, Error> {
        Self::new(v.name, v.scope, v.minimum, v.maximum)
    }
}
impl From<Source> for SourceDefinition {
    fn from(v: Source) -> Self {
        Self {
            name: v.name,
            scope: v.scope,
            minimum: v.minimum,
            maximum: v.maximum,
        }
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PointDefinition {
    input: f64,
    amount: f64,
}
impl TryFrom<PointDefinition> for Point {
    type Error = Error;
    fn try_from(v: PointDefinition) -> Result<Self, Error> {
        Self::new(v.input, v.amount)
    }
}
impl From<Point> for PointDefinition {
    fn from(v: Point) -> Self {
        Self {
            input: v.input,
            amount: v.amount,
        }
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RoutePoint {
    input: f64,
    amount: ScalarInput,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RouteDefinition {
    name: Identifier,
    source: Identifier,
    target: Target,
    operation: Operation,
    unit: Unit,
    points: Vec<RoutePoint>,
    #[serde(default)]
    interpolation: Interpolation,
}
impl TryFrom<RouteDefinition> for Route {
    type Error = Error;
    fn try_from(v: RouteDefinition) -> Result<Self, Error> {
        v.prepare(quantity::MAX_RECORDS)
    }
}
impl RouteDefinition {
    fn prepare(self, maximum: usize) -> Result<Route, Error> {
        quantity::record_budget(
            self.points
                .len()
                .checked_add(1)
                .ok_or(Error::ArithmeticRange)?,
            maximum,
        )?;
        let points = self
            .points
            .into_iter()
            .map(|p| Point::new(p.input, p.amount.normalize(self.unit)?))
            .collect::<Result<_, _>>()?;
        Route {
            name: self.name,
            source: self.source,
            target: self.target,
            operation: self.operation,
            unit: self.unit,
            points,
            interpolation: self.interpolation,
        }
        .checked(maximum)
    }
}
impl From<Route> for RouteDefinition {
    fn from(v: Route) -> Self {
        Self {
            name: v.name,
            source: v.source,
            target: v.target,
            operation: v.operation,
            unit: v.unit,
            points: v
                .points
                .into_iter()
                .map(|p| RoutePoint {
                    input: p.input,
                    amount: ScalarInput::Number(p.amount),
                })
                .collect(),
            interpolation: v.interpolation,
        }
    }
}
#[derive(Default, Clone, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
struct ModulationDefinition {
    parameters: Vec<ParameterDefinition>,
    sources: Vec<SourceDefinition>,
    routes: Vec<RouteDefinition>,
}
impl TryFrom<ModulationDefinition> for Modulation {
    type Error = Error;
    fn try_from(v: ModulationDefinition) -> Result<Self, Error> {
        v.prepare(quantity::MAX_RECORDS)
    }
}
impl ModulationDefinition {
    fn prepare(self, maximum: usize) -> Result<Modulation, Error> {
        let mut count = 0_usize;
        for length in [self.parameters.len(), self.sources.len(), self.routes.len()] {
            count = count.checked_add(length).ok_or(Error::ArithmeticRange)?;
            quantity::record_budget(count, maximum)?;
        }
        for route in &self.routes {
            count = count
                .checked_add(route.points.len())
                .ok_or(Error::ArithmeticRange)?;
            quantity::record_budget(count, maximum)?;
        }
        Modulation {
            parameters: self
                .parameters
                .into_iter()
                .map(Parameter::try_from)
                .collect::<Result<_, _>>()?,
            sources: self
                .sources
                .into_iter()
                .map(Source::try_from)
                .collect::<Result<_, _>>()?,
            routes: self
                .routes
                .into_iter()
                .map(|r| r.prepare(maximum))
                .collect::<Result<_, _>>()?,
        }
        .checked(maximum)
    }
}
impl From<Modulation> for ModulationDefinition {
    fn from(v: Modulation) -> Self {
        Self {
            parameters: v.parameters.into_iter().map(Into::into).collect(),
            sources: v.sources.into_iter().map(Into::into).collect(),
            routes: v.routes.into_iter().map(Into::into).collect(),
        }
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SourceValueDefinition {
    value: f64,
    #[serde(default = "weight")]
    weight: f64,
}
impl TryFrom<SourceValueDefinition> for SourceValue {
    type Error = Error;
    fn try_from(v: SourceValueDefinition) -> Result<Self, Error> {
        Self::new(v.value, v.weight)
    }
}
impl From<SourceValue> for SourceValueDefinition {
    fn from(v: SourceValue) -> Self {
        Self {
            value: v.value,
            weight: v.weight,
        }
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ParameterValueDefinition {
    target: Target,
    value: f64,
}
impl TryFrom<ParameterValueDefinition> for ParameterValue {
    type Error = Error;
    fn try_from(v: ParameterValueDefinition) -> Result<Self, Error> {
        Self::new(v.target, v.value)
    }
}
impl From<ParameterValue> for ParameterValueDefinition {
    fn from(v: ParameterValue) -> Self {
        Self {
            target: v.target,
            value: v.value,
        }
    }
}
