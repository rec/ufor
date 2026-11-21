//! Validated finite pitches and repeating or finite ratios.

use serde::{Deserialize, Deserializer, Serialize, Serializer};

use crate::error::Error;
use crate::expression::evaluate;
use crate::number::Number;
use crate::units;

pub const MAX_TABLE_ENTRIES: usize = 10_000;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "ComputedDefinition", into = "ComputedDefinition")]
pub struct Computed {
    definition: ComputedDefinition,
    period: Number,
}

impl Computed {
    pub fn notes_per_octave(&self) -> i64 {
        self.definition.notes_per_octave
    }
    pub fn octave_ratio(&self) -> &str {
        &self.definition.octave_ratio
    }
    pub fn denominator_limit(&self) -> i64 {
        self.definition.denominator_limit
    }

    pub fn new(
        notes_per_octave: i64,
        octave_ratio: String,
        denominator_limit: i64,
    ) -> Result<Self, Error> {
        if notes_per_octave < 1 || denominator_limit < 0 {
            return Err(Error::Invalid(
                "note count must be positive and denominator limit nonnegative".into(),
            ));
        }
        let period = evaluate(&octave_ratio)?.positive()?;
        Ok(Self {
            definition: ComputedDefinition {
                notes_per_octave,
                octave_ratio,
                denominator_limit,
            },
            period,
        })
    }

    pub fn evaluate(&self, degree: i64) -> Result<Number, Error> {
        let ratio = self
            .period
            .checked_pow(Number::exact(degree, self.definition.notes_per_octave)?)?;
        if self.definition.denominator_limit == 0 {
            ratio.positive()
        } else {
            ratio
                .limit_denominator(self.definition.denominator_limit)?
                .positive()
        }
    }

    pub fn as_ratios(&self) -> Result<RatioTable, Error> {
        if self.definition.notes_per_octave > MAX_TABLE_ENTRIES as i64 {
            return Err(Error::Limit("table entries"));
        }
        let values = (0..self.definition.notes_per_octave)
            .map(|i| self.evaluate(i).map(|v| v.to_string()))
            .collect::<Result<_, _>>()?;
        RatioTable::new(
            values,
            Some(self.evaluate(self.definition.notes_per_octave)?.to_string()),
            String::new(),
            String::new(),
        )
    }
}

impl Default for Computed {
    fn default() -> Self {
        Self::new(12, "2".into(), 0).expect("valid default computed tuning")
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "RatioDefinition", into = "RatioDefinition")]
pub struct RatioTable {
    definition: RatioDefinition,
    ratios: Vec<Number>,
    period: Option<Number>,
}

impl RatioTable {
    pub fn new(
        values: Vec<String>,
        repeat_ratio: Option<String>,
        name: String,
        description: String,
    ) -> Result<Self, Error> {
        let ratios = positive_values(&values)?;
        let period = repeat_ratio
            .as_deref()
            .map(|v| evaluate(v)?.positive())
            .transpose()?;
        Ok(Self {
            definition: RatioDefinition {
                ratios: values,
                repeat_ratio,
                name,
                description,
            },
            ratios,
            period,
        })
    }

    pub fn ratios(&self) -> &[String] {
        &self.definition.ratios
    }
    pub fn repeat_ratio(&self) -> Option<&str> {
        self.definition.repeat_ratio.as_deref()
    }
    pub fn name(&self) -> &str {
        &self.definition.name
    }
    pub fn description(&self) -> &str {
        &self.definition.description
    }

    pub fn evaluate(&self, degree: i64) -> Result<Number, Error> {
        let length = self.ratios.len() as i64;
        if let Some(period) = self.period {
            let cycle = degree.div_euclid(length);
            let offset = degree.rem_euclid(length) as usize;
            period
                .checked_pow(Number::exact(cycle, 1)?)?
                .checked_mul(self.ratios[offset])?
                .positive()
        } else {
            let index = usize::try_from(degree).map_err(|_| Error::OutsideDomain)?;
            self.ratios.get(index).copied().ok_or(Error::OutsideDomain)
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "IntervalDefinition", into = "IntervalDefinition")]
pub struct IntervalPattern {
    definition: IntervalDefinition,
    ratios: Vec<Number>,
}

impl IntervalPattern {
    pub fn new(intervals: Vec<String>, repeat: bool) -> Result<Self, Error> {
        let ratios = positive_values(&intervals)?;
        Ok(Self {
            definition: IntervalDefinition { intervals, repeat },
            ratios,
        })
    }

    pub fn intervals(&self) -> &[String] {
        &self.definition.intervals
    }
    pub fn repeats(&self) -> bool {
        self.definition.repeat
    }

    pub fn evaluate(&self, degree: i64) -> Result<Number, Error> {
        let length = self.ratios.len() as i64;
        if !self.definition.repeat {
            if !(0..=length).contains(&degree) {
                return Err(Error::OutsideDomain);
            }
            return product(&self.ratios[..degree as usize])?.positive();
        }
        let cycle = degree.div_euclid(length);
        let offset = degree.rem_euclid(length) as usize;
        product(&self.ratios)?
            .checked_pow(Number::exact(cycle, 1)?)?
            .checked_mul(product(&self.ratios[..offset])?)?
            .positive()
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "FrequencyDefinition", into = "FrequencyDefinition")]
pub struct FrequencyTable {
    definition: FrequencyDefinition,
    frequencies: Vec<Number>,
}

impl FrequencyTable {
    pub fn new(values: Vec<String>, first_note: i64) -> Result<Self, Error> {
        table_length(values.len())?;
        let values = values
            .iter()
            .map(|v| units::frequency(v))
            .collect::<Result<Vec<_>, _>>()?;
        let frequencies = positive_values(&values)?;
        Ok(Self {
            definition: FrequencyDefinition {
                frequencies: values,
                first_note,
            },
            frequencies,
        })
    }

    pub fn frequencies(&self) -> &[String] {
        &self.definition.frequencies
    }
    pub fn first_note(&self) -> i64 {
        self.definition.first_note
    }

    pub fn evaluate(&self, note: i64) -> Result<Number, Error> {
        let index = note
            .checked_sub(self.definition.first_note)
            .and_then(|v| usize::try_from(v).ok())
            .ok_or(Error::OutsideDomain)?;
        self.frequencies
            .get(index)
            .copied()
            .ok_or(Error::OutsideDomain)
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum Source {
    Computed(Computed),
    Ratios(RatioTable),
    Intervals(IntervalPattern),
    Frequencies(FrequencyTable),
}

impl Source {
    pub fn evaluate(&self, degree: i64) -> Result<Number, Error> {
        match self {
            Self::Computed(value) => value.evaluate(degree),
            Self::Ratios(value) => value.evaluate(degree),
            Self::Intervals(value) => value.evaluate(degree),
            Self::Frequencies(value) => value.evaluate(degree),
        }
    }
}

impl Serialize for Source {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match self {
            Self::Computed(value) => value.serialize(serializer),
            Self::Ratios(value) => value.serialize(serializer),
            Self::Intervals(value) => value.serialize(serializer),
            Self::Frequencies(value) => value.serialize(serializer),
        }
    }
}

impl<'de> Deserialize<'de> for Source {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let result = match SourceDefinition::deserialize(deserializer)? {
            SourceDefinition::Computed(value) => Computed::try_from(value).map(Self::Computed),
            SourceDefinition::Ratios(value) => RatioTable::try_from(value).map(Self::Ratios),
            SourceDefinition::Intervals(value) => {
                IntervalPattern::try_from(value).map(Self::Intervals)
            }
            SourceDefinition::Frequencies(value) => {
                FrequencyTable::try_from(value).map(Self::Frequencies)
            }
        };
        result.map_err(serde::de::Error::custom)
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "TuningDefinition", into = "TuningDefinition")]
pub struct Tuning {
    source: Source,
    root_note: i64,
    root_frequency: String,
    anchor: Number,
    detune_cents: f64,
}

impl Tuning {
    pub fn new(
        source: Source,
        root_note: i64,
        root_frequency: String,
        detune_cents: f64,
    ) -> Result<Self, Error> {
        if !detune_cents.is_finite() {
            return Err(Error::ArithmeticRange);
        }
        let root_frequency = units::frequency(&root_frequency)?;
        let anchor = evaluate(&root_frequency)?.positive()?;
        Ok(Self {
            source,
            root_note,
            root_frequency,
            anchor,
            detune_cents,
        })
    }

    pub fn source(&self) -> &Source {
        &self.source
    }
    pub fn root_note(&self) -> i64 {
        self.root_note
    }
    pub fn root_frequency(&self) -> &str {
        &self.root_frequency
    }
    pub fn detune_cents(&self) -> f64 {
        self.detune_cents
    }

    pub fn evaluate(&self, note: i64) -> Result<Number, Error> {
        let frequency = if matches!(self.source, Source::Frequencies(_)) {
            self.source.evaluate(note)?
        } else {
            let degree = note
                .checked_sub(self.root_note)
                .ok_or(Error::ArithmeticRange)?;
            self.anchor.checked_mul(self.source.evaluate(degree)?)?
        };
        if self.detune_cents == 0.0 {
            return frequency.positive();
        }
        frequency
            .checked_mul(Number::approximate((self.detune_cents / 1200.0).exp2())?)?
            .positive()
    }
}

fn table_length(length: usize) -> Result<(), Error> {
    if length == 0 {
        return Err(Error::Invalid("table must not be empty".into()));
    }
    if length > MAX_TABLE_ENTRIES {
        return Err(Error::Limit("table entries"));
    }
    Ok(())
}

fn positive_values(values: &[String]) -> Result<Vec<Number>, Error> {
    table_length(values.len())?;
    values.iter().map(|v| evaluate(v)?.positive()).collect()
}

fn product(values: &[Number]) -> Result<Number, Error> {
    values
        .iter()
        .try_fold(Number::exact(1, 1)?, |a, v| a.checked_mul(*v))
}

fn root_note() -> i64 {
    69
}
fn root_frequency() -> String {
    "440".into()
}
fn repeating() -> bool {
    true
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
struct ComputedDefinition {
    denominator_limit: i64,
    notes_per_octave: i64,
    octave_ratio: String,
}

impl Default for ComputedDefinition {
    fn default() -> Self {
        Self {
            denominator_limit: 0,
            notes_per_octave: 12,
            octave_ratio: "2".into(),
        }
    }
}

impl TryFrom<ComputedDefinition> for Computed {
    type Error = Error;
    fn try_from(value: ComputedDefinition) -> Result<Self, Error> {
        Self::new(
            value.notes_per_octave,
            value.octave_ratio,
            value.denominator_limit,
        )
    }
}
impl From<Computed> for ComputedDefinition {
    fn from(value: Computed) -> Self {
        value.definition
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RatioDefinition {
    ratios: Vec<String>,
    #[serde(default)]
    repeat_ratio: Option<String>,
    #[serde(default)]
    name: String,
    #[serde(default)]
    description: String,
}
impl TryFrom<RatioDefinition> for RatioTable {
    type Error = Error;
    fn try_from(value: RatioDefinition) -> Result<Self, Error> {
        Self::new(
            value.ratios,
            value.repeat_ratio,
            value.name,
            value.description,
        )
    }
}
impl From<RatioTable> for RatioDefinition {
    fn from(value: RatioTable) -> Self {
        value.definition
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct IntervalDefinition {
    intervals: Vec<String>,
    #[serde(default = "repeating")]
    repeat: bool,
}
impl TryFrom<IntervalDefinition> for IntervalPattern {
    type Error = Error;
    fn try_from(value: IntervalDefinition) -> Result<Self, Error> {
        Self::new(value.intervals, value.repeat)
    }
}
impl From<IntervalPattern> for IntervalDefinition {
    fn from(value: IntervalPattern) -> Self {
        value.definition
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct FrequencyDefinition {
    frequencies: Vec<String>,
    #[serde(default)]
    first_note: i64,
}
impl TryFrom<FrequencyDefinition> for FrequencyTable {
    type Error = Error;
    fn try_from(value: FrequencyDefinition) -> Result<Self, Error> {
        Self::new(value.frequencies, value.first_note)
    }
}
impl From<FrequencyTable> for FrequencyDefinition {
    fn from(value: FrequencyTable) -> Self {
        value.definition
    }
}

#[derive(Deserialize)]
#[serde(untagged)]
enum SourceDefinition {
    Computed(ComputedDefinition),
    Ratios(RatioDefinition),
    Intervals(IntervalDefinition),
    Frequencies(FrequencyDefinition),
}

#[derive(Serialize, Deserialize)]
#[serde(untagged)]
enum Detuning {
    Number(f64),
    Text(String),
}
impl Default for Detuning {
    fn default() -> Self {
        Self::Number(0.0)
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct TuningDefinition {
    source: Source,
    #[serde(default = "root_note")]
    root_note: i64,
    #[serde(default = "root_frequency")]
    root_frequency: String,
    #[serde(default)]
    detune_cents: Detuning,
}
impl TryFrom<TuningDefinition> for Tuning {
    type Error = Error;
    fn try_from(value: TuningDefinition) -> Result<Self, Error> {
        let detune = match value.detune_cents {
            Detuning::Number(v) => v,
            Detuning::Text(v) => units::cents(&v)?,
        };
        Self::new(value.source, value.root_note, value.root_frequency, detune)
    }
}
impl From<Tuning> for TuningDefinition {
    fn from(value: Tuning) -> Self {
        Self {
            source: value.source,
            root_note: value.root_note,
            root_frequency: value.root_frequency,
            detune_cents: Detuning::Number(value.detune_cents),
        }
    }
}
