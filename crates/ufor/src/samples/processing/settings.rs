//! Shared processing declarations and authored target resolution.
#![doc = include_str!("../../../../../doc/rust-sound-settings.md")]
use super::{Binding, EnvelfoEventConnection, invalid};
use crate::control::{Polarity, Scope};
use crate::envelfo::wire::{Ordered, RootWire};
use crate::envelfo::{self, Body, Clock, EnvelopeSegment, Generator, PreparationLimits};
use crate::error::Error;
use crate::identifier::Identifier;
use crate::modulation::{Modulation, ModulationDefinition, Operation, Target, Unit};
use crate::number::Rational;
use crate::quantity;
use crate::samples::bindings::{BindingValidation, validate_available_bindings};
use crate::samples::controls::ControlDeclaration;
use serde::{Deserialize, Deserializer, Serialize};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FilterResponse {
    Lowpass,
    Highpass,
    Bandpass,
    Notch,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FilterBoundary {
    #[default]
    Error,
    Clamp,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FilterOrder {
    #[default]
    BeforeAmplitude,
    AfterAmplitude,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EqualizerBand {
    name: Identifier,
    #[serde(deserialize_with = "hertz")]
    frequency_hz: f64,
    #[serde(deserialize_with = "decibels")]
    gain_db: f64,
    #[serde(deserialize_with = "positive")]
    resonance: f64,
}

impl EqualizerBand {
    pub fn name(&self) -> &Identifier {
        &self.name
    }
    pub fn frequency_hz(&self) -> f64 {
        self.frequency_hz
    }
    pub fn gain_db(&self) -> f64 {
        self.gain_db
    }
    pub fn resonance(&self) -> f64 {
        self.resonance
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct FilterTolerance {
    #[serde(deserialize_with = "positive")]
    coefficient: f64,
    #[serde(deserialize_with = "positive_db")]
    response_db: f64,
}

impl Default for FilterTolerance {
    fn default() -> Self {
        Self {
            coefficient: 1e-12,
            response_db: 1e-6,
        }
    }
}

impl FilterTolerance {
    pub fn coefficient(&self) -> f64 {
        self.coefficient
    }
    pub fn response_db(&self) -> f64 {
        self.response_db
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResonantFilter {
    name: Identifier,
    response: FilterResponse,
    #[serde(deserialize_with = "hertz")]
    cutoff_hz: f64,
    #[serde(default = "default_q", deserialize_with = "positive")]
    q: f64,
    #[serde(default = "one_stage", deserialize_with = "filter_stages")]
    stages: u8,
    #[serde(default)]
    boundary: FilterBoundary,
    #[serde(default = "minimum_hz", deserialize_with = "hertz")]
    minimum_hz: f64,
    #[serde(default = "nyquist_ratio", deserialize_with = "filter_nyquist")]
    nyquist_ratio: f64,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "tolerance"
    )]
    tolerance: Option<FilterTolerance>,
}

impl ResonantFilter {
    pub fn name(&self) -> &Identifier {
        &self.name
    }
    pub fn response(&self) -> FilterResponse {
        self.response
    }
    pub fn cutoff_hz(&self) -> f64 {
        self.cutoff_hz
    }
    pub fn q(&self) -> f64 {
        self.q
    }
    pub fn stages(&self) -> u8 {
        self.stages
    }
    pub fn boundary(&self) -> FilterBoundary {
        self.boundary
    }
    pub fn minimum_hz(&self) -> f64 {
        self.minimum_hz
    }
    pub fn nyquist_ratio(&self) -> f64 {
        self.nyquist_ratio
    }
    pub fn tolerance(&self) -> FilterTolerance {
        self.tolerance.clone().unwrap_or_default()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Processing {
    #[serde(deserialize_with = "decibels")]
    volume_db: f64,
    invert_polarity: bool,
    #[serde(deserialize_with = "cents")]
    tuning_cents: f64,
    #[serde(deserialize_with = "finite_number")]
    pan: f64,
    #[serde(deserialize_with = "finite_number")]
    stereo_balance: f64,
    #[serde(deserialize_with = "equalizer")]
    equalizer: Vec<EqualizerBand>,
    #[serde(deserialize_with = "filters")]
    filters: Vec<ResonantFilter>,
    filter_order: FilterOrder,
}

impl Processing {
    pub fn volume_db(&self) -> f64 {
        self.volume_db
    }
    pub fn invert_polarity(&self) -> bool {
        self.invert_polarity
    }
    pub fn tuning_cents(&self) -> f64 {
        self.tuning_cents
    }
    pub fn pan(&self) -> f64 {
        self.pan
    }
    pub fn stereo_balance(&self) -> f64 {
        self.stereo_balance
    }
    pub fn equalizer(&self) -> &[EqualizerBand] {
        &self.equalizer
    }
    pub fn filters(&self) -> &[ResonantFilter] {
        &self.filters
    }
    pub fn filter_order(&self) -> FilterOrder {
        self.filter_order
    }
}

/// A base SoundSettings body with authored declarations in wire order.
#[derive(Clone, Debug, Serialize)]
pub struct SoundSettings {
    #[serde(skip_serializing_if = "Option::is_none")]
    processing: Option<Processing>,
    #[serde(skip_serializing_if = "Option::is_none")]
    envelope: Option<Generator>,
    envelfos: Ordered<Generator>,
    #[serde(skip_serializing_if = "Option::is_none")]
    modulation: Option<Modulation>,
    bindings: Vec<Binding>,
    event_connections: Vec<EnvelfoEventConnection>,
    #[serde(skip)]
    records: usize,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ResolvedTarget {
    pub unit: Unit,
    pub default_value: f64,
    pub duration: Option<Rational>,
    pub scope: Option<Scope>,
    pub minimum: TargetMinimum,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TargetMinimum {
    Unrestricted,
    Nonnegative,
    Positive,
}

impl TargetMinimum {
    fn for_field(field: &str) -> Self {
        match field {
            "amplitude" => Self::Nonnegative,
            "resonance" | "q" => Self::Positive,
            _ => Self::Unrestricted,
        }
    }

    fn validate(self, minimum: f64) -> Result<(), Error> {
        match self {
            Self::Nonnegative if minimum < 0.0 => {
                Err(invalid("amplitude requires a nonnegative domain"))
            }
            Self::Positive if minimum <= 0.0 => {
                Err(invalid("resonance requires a positive domain"))
            }
            _ => Ok(()),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum TargetResolution {
    Resolved(ResolvedTarget),
    UnresolvedGenerator { scope: Scope },
}

#[derive(Clone, Debug, PartialEq)]
pub struct SoundValidation {
    pub unresolved_controls: Vec<Identifier>,
    pub generator_checks: BindingValidation,
}

impl SoundValidation {
    pub fn is_complete(&self) -> bool {
        self.unresolved_controls.is_empty()
            && self.generator_checks.unresolved_bindings().is_empty()
            && self.generator_checks.unresolved_connections().is_empty()
            && self.generator_checks.unresolved_targets().is_empty()
    }

    pub fn require_complete(&self) -> Result<(), Error> {
        if self.is_complete() {
            Ok(())
        } else {
            Err(invalid("sound settings need external context"))
        }
    }
}

impl SoundSettings {
    pub fn processing(&self) -> &Processing {
        static DEFAULT: std::sync::LazyLock<Processing> =
            std::sync::LazyLock::new(Processing::default);
        self.processing.as_ref().unwrap_or(&DEFAULT)
    }
    pub fn envelope(&self) -> Option<&Generator> {
        self.envelope.as_ref()
    }
    pub fn envelfos(&self) -> &[(Identifier, Generator)] {
        &self.envelfos.0
    }
    pub fn modulation(&self) -> &Modulation {
        static DEFAULT: std::sync::LazyLock<Modulation> =
            std::sync::LazyLock::new(Modulation::default);
        self.modulation.as_ref().unwrap_or(&DEFAULT)
    }
    pub fn bindings(&self) -> &[Binding] {
        &self.bindings
    }
    pub fn event_connections(&self) -> &[EnvelfoEventConnection] {
        &self.event_connections
    }

    pub fn resolve_target(&self, target: &Target) -> Result<TargetResolution, Error> {
        let name = target.name().as_str();
        let field = target.parameter().as_str();
        let p = self.processing();
        let ordinary = match name {
            "processing" => match field {
                "amplitude" => Some((Unit::Ratio, 1.0)),
                "volume_db" => Some((Unit::Db, p.volume_db)),
                "tuning_cents" => Some((Unit::Cents, p.tuning_cents)),
                "pan" => Some((Unit::Normalized, p.pan)),
                "stereo_balance" => Some((Unit::Normalized, p.stereo_balance)),
                _ => None,
            },
            _ if name.starts_with("eq-") => p
                .equalizer
                .iter()
                .find(|b| b.name.as_str() == &name[3..])
                .and_then(|b| match field {
                    "gain_db" => Some((Unit::Db, b.gain_db)),
                    "frequency_hz" => Some((Unit::Hz, b.frequency_hz)),
                    "resonance" => Some((Unit::Ratio, b.resonance)),
                    _ => None,
                }),
            _ if name.starts_with("filter-") => p
                .filters
                .iter()
                .find(|f| f.name.as_str() == &name[7..])
                .and_then(|f| match field {
                    "cutoff_hz" => Some((Unit::Hz, f.cutoff_hz)),
                    "q" => Some((Unit::Ratio, f.q)),
                    _ => None,
                }),
            _ => None,
        };
        if let Some((unit, default_value)) = ordinary {
            return Ok(TargetResolution::Resolved(ResolvedTarget {
                unit,
                default_value,
                duration: None,
                scope: None,
                minimum: TargetMinimum::for_field(field),
            }));
        }
        let generator = if name == "envelope" {
            self.envelope.as_ref()
        } else {
            name.strip_prefix("envelfo-").and_then(|name| {
                self.envelfos
                    .0
                    .iter()
                    .find(|(id, _)| id.as_str() == name)
                    .map(|(_, value)| value)
            })
        }
        .ok_or_else(|| unknown(target))?;
        let scope = generator.settings().scope();
        let body = match generator.body() {
            Body::Reference(_) => return Ok(TargetResolution::UnresolvedGenerator { scope }),
            Body::Envelope(body) => body,
            _ => return Err(unknown(target)),
        };
        let (phase, address) = field.split_once('-').ok_or_else(|| unknown(target))?;
        let (index, parameter) = address.split_once('-').ok_or_else(|| unknown(target))?;
        let position = index
            .parse::<usize>()
            .ok()
            .filter(|v| v.to_string() == index)
            .ok_or_else(|| unknown(target))?;
        let segment = match phase {
            "on" => body.segments().get(position),
            "release" => body.release().get(position),
            _ => None,
        }
        .ok_or_else(|| unknown(target))?;
        let (unit, default_value, duration) = match (parameter, segment) {
            ("duration", EnvelopeSegment::Definite(segment)) => {
                let duration = segment.duration();
                let unit = match generator.settings().clock() {
                    Clock::Seconds => Unit::Seconds,
                    Clock::Beats => Unit::Beats,
                };
                (unit, duration_default(duration), Some(duration))
            }
            ("time_constant", EnvelopeSegment::Approach(segment)) => {
                (Unit::Seconds, segment.time_constant(), None)
            }
            ("duration", _) => return Err(invalid("segment duration cannot be modulated")),
            _ => return Err(unknown(target)),
        };
        Ok(TargetResolution::Resolved(ResolvedTarget {
            unit,
            default_value,
            duration,
            scope: Some(scope),
            minimum: TargetMinimum::Unrestricted,
        }))
    }

    /// Validate supplied instrument controls and report obligations in declaration order.
    pub fn validate_context(
        &self,
        controls: Option<&BTreeMap<Identifier, ControlDeclaration>>,
        limits: PreparationLimits,
    ) -> Result<SoundValidation, Error> {
        limits.check_records(
            self.records
                .checked_add(controls.map_or(0, BTreeMap::len))
                .ok_or(Error::ArithmeticRange)?,
        )?;
        let mut generator_checks = validate_available_bindings(
            self.modulation(),
            &self.bindings,
            controls,
            &self.envelfos.0.iter().cloned().collect(),
            &self.event_connections,
            limits,
        )?;
        if self
            .bindings
            .iter()
            .any(|b| matches!(b, Binding::Follower(_)))
        {
            return Err(invalid("follower bindings require an effect graph"));
        }
        let mut outstanding = Vec::new();
        for parameter in self.modulation().parameters() {
            let target = parameter.target();
            match self.resolve_target(target)? {
                TargetResolution::Resolved(value) => {
                    if parameter.unit() != value.unit
                        || parameter.default_value() != value.default_value
                    {
                        return Err(invalid(
                            "parameter unit and default must match the bound setting",
                        ));
                    }
                    if value.scope.is_some_and(|scope| scope != parameter.scope()) {
                        return Err(invalid(
                            "Envelope parameter scope must match its definition",
                        ));
                    }
                }
                TargetResolution::UnresolvedGenerator { scope } => {
                    if scope != parameter.scope() {
                        return Err(invalid("Envelfo parameter scope must match its use"));
                    }
                    outstanding.push(target.clone());
                }
            }
            TargetMinimum::for_field(target.parameter().as_str()).validate(parameter.minimum())?;
        }
        let event_sources: BTreeSet<_> = self
            .bindings
            .iter()
            .filter_map(|b| match b {
                Binding::Event(b) => Some(b.name()),
                _ => None,
            })
            .collect();
        for route in self.modulation().routes() {
            if route.operation() == Operation::Multiply
                && route.points().iter().any(|p| p.amount() < 0.0)
            {
                return Err(invalid("sound processing multipliers must be nonnegative"));
            }
            let name = route.target().name().as_str();
            if (name == "envelope" || name.starts_with("envelfo-"))
                && !event_sources.contains(route.source())
            {
                return Err(invalid(
                    "Envelope parameters require key or velocity latching",
                ));
            }
        }
        generator_checks.unresolved_targets = outstanding;
        let unresolved_controls = if controls.is_none() {
            self.bindings
                .iter()
                .filter_map(|b| match b {
                    Binding::Control(b) => Some(b.control().clone()),
                    _ => None,
                })
                .collect()
        } else {
            Vec::new()
        };
        Ok(SoundValidation {
            unresolved_controls,
            generator_checks,
        })
    }

    pub(crate) fn decode<'de, D: Deserializer<'de>>(
        d: D,
        limits: PreparationLimits,
    ) -> Result<Self, D::Error> {
        let wire = SoundWire::deserialize(d)?;
        let data = serde_json::to_value(&wire).map_err(serde::de::Error::custom)?;
        let records =
            envelfo::preparation_records(&data, limits).map_err(serde::de::Error::custom)?;
        wire.prepare(limits, records)
            .map_err(serde::de::Error::custom)
    }
}

impl<'de> Deserialize<'de> for SoundSettings {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        Self::decode(d, PreparationLimits::default())
    }
}

#[derive(Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
struct SoundWire {
    #[serde(deserialize_with = "processing")]
    processing: Option<Processing>,
    envelope: Option<serde_json::Value>,
    envelfos: Ordered<RootWire>,
    #[serde(deserialize_with = "modulation")]
    modulation: Option<ModulationDefinition>,
    bindings: Vec<Binding>,
    event_connections: Vec<EnvelfoEventConnection>,
}

impl SoundWire {
    fn prepare(self, limits: PreparationLimits, records: usize) -> Result<SoundSettings, Error> {
        let envelope = self.envelope.map(|value| {
            let generator = RootWire::envelope(value)?;
            if !matches!(generator.body(), Body::Envelope(body) if body.polarity() == Polarity::Unipolar)
                || generator.settings().scope() != Scope::Voice {
                return Err(invalid("amplitude Envelope requires voice scope and unipolar levels"));
            }
            Ok(generator)
        }).transpose()?;
        let value = SoundSettings {
            processing: self.processing,
            envelope,
            envelfos: Ordered(
                self.envelfos
                    .0
                    .into_iter()
                    .map(|(name, raw)| Ok((name, raw.prepare()?)))
                    .collect::<Result<_, Error>>()?,
            ),
            modulation: self
                .modulation
                .map(|m| m.prepare(limits.max_records()))
                .transpose()?,
            bindings: self.bindings,
            event_connections: self.event_connections,
            records,
        };
        value.validate_context(None, limits)?;
        Ok(value)
    }
}

fn unknown(target: &Target) -> Error {
    invalid(&format!(
        "unknown local parameter: {}.{}",
        target.name().as_str(),
        target.parameter().as_str()
    ))
}

// Match Python's float(Fraction) without rounding the integer operands first.
// Envelope durations are nonnegative, with signed-64-bit rational components.
fn duration_default(value: Rational) -> f64 {
    let numerator = value.numerator() as u128;
    if numerator == 0 {
        return 0.0;
    }
    let denominator = value.denominator() as u128;
    let estimate = denominator.leading_zeros() as i32 - numerator.leading_zeros() as i32;
    let below = if estimate >= 0 {
        numerator < denominator << estimate
    } else {
        numerator << -estimate < denominator
    };
    let exponent = estimate - i32::from(below);
    let shift = 52 - exponent;
    let (n, d) = if shift >= 0 {
        (numerator << shift, denominator)
    } else {
        (numerator, denominator << -shift)
    };
    let significand = n / d;
    let remainder = n % d;
    let round_up = 2 * remainder > d || (2 * remainder == d && significand % 2 != 0);
    (significand + u128::from(round_up)) as f64 * 2.0_f64.powi(-shift)
}

fn default_q() -> f64 {
    1.0 / 2.0_f64.sqrt()
}
fn one_stage() -> u8 {
    1
}
fn minimum_hz() -> f64 {
    1.0
}
fn nyquist_ratio() -> f64 {
    0.999
}

fn filter_stages<'de, D: Deserializer<'de>>(d: D) -> Result<u8, D::Error> {
    let value = u8::deserialize(d)?;
    if matches!(value, 1 | 2) {
        Ok(value)
    } else {
        Err(serde::de::Error::custom("filter stages must be 1 or 2"))
    }
}
fn filter_nyquist<'de, D: Deserializer<'de>>(d: D) -> Result<f64, D::Error> {
    let value = f64::deserialize(d)?;
    if value > 0.0 && value < 1.0 {
        Ok(value)
    } else {
        Err(serde::de::Error::custom(
            "Nyquist ratio must be between zero and one",
        ))
    }
}
fn tolerance<'de, D: Deserializer<'de>>(d: D) -> Result<Option<FilterTolerance>, D::Error> {
    FilterTolerance::deserialize(d).map(Some)
}
fn processing<'de, D: Deserializer<'de>>(d: D) -> Result<Option<Processing>, D::Error> {
    Processing::deserialize(d).map(Some)
}
fn modulation<'de, D: Deserializer<'de>>(d: D) -> Result<Option<ModulationDefinition>, D::Error> {
    ModulationDefinition::deserialize(d).map(Some)
}
fn equalizer<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<EqualizerBand>, D::Error> {
    let values = Vec::<EqualizerBand>::deserialize(d)?;
    if values
        .iter()
        .map(|b| &b.name)
        .collect::<BTreeSet<_>>()
        .len()
        != values.len()
    {
        return Err(serde::de::Error::custom("duplicate EQ band name"));
    }
    Ok(values)
}
fn filters<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<ResonantFilter>, D::Error> {
    let values = Vec::<ResonantFilter>::deserialize(d)?;
    if values
        .iter()
        .map(|f| &f.name)
        .collect::<BTreeSet<_>>()
        .len()
        != values.len()
    {
        return Err(serde::de::Error::custom("duplicate filter name"));
    }
    Ok(values)
}

fn finite_number<'de, D: Deserializer<'de>>(d: D) -> Result<f64, D::Error> {
    quantity::finite(f64::deserialize(d)?).map_err(serde::de::Error::custom)
}
fn positive<'de, D: Deserializer<'de>>(d: D) -> Result<f64, D::Error> {
    require_positive(finite_number(d)?)
}
fn hertz<'de, D: Deserializer<'de>>(d: D) -> Result<f64, D::Error> {
    require_positive(quantity::deserialize_scalar(d, "hz")?)
}
fn positive_db<'de, D: Deserializer<'de>>(d: D) -> Result<f64, D::Error> {
    require_positive(quantity::deserialize_scalar(d, "db")?)
}
fn decibels<'de, D: Deserializer<'de>>(d: D) -> Result<f64, D::Error> {
    quantity::deserialize_scalar(d, "db")
}
fn cents<'de, D: Deserializer<'de>>(d: D) -> Result<f64, D::Error> {
    quantity::deserialize_scalar(d, "cents")
}
fn require_positive<E: serde::de::Error>(value: f64) -> Result<f64, E> {
    if value > 0.0 {
        Ok(value)
    } else {
        Err(E::custom("expected a positive scalar"))
    }
}
