//! Portable generator definitions and preparation, without generator execution.
#![doc = include_str!("../../../doc/rust-envelfo.md")]

mod validation;
pub(crate) mod wire;

use crate::control::{Polarity, Scope};
use crate::error::Error;
use crate::identifier::Identifier;
use crate::modulation::Unit;
use crate::number::Rational;
use crate::quantity::finite;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::Value;
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Clock {
    #[default]
    Seconds,
    Beats,
}
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PositionDriver {
    #[default]
    Elapsed,
    Transport,
}
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Waveform {
    #[default]
    Sine,
    Square,
    Triangle,
}
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Reset {
    #[default]
    Trigger,
    Transport,
    Free,
}
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Retrigger {
    Reset,
    #[default]
    Current,
    Ignore,
}
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PlaybackMode {
    #[default]
    Once,
    Loop,
    PingPong,
}
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Start {
    #[default]
    Activation,
    Event,
}
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EventAction {
    #[default]
    Start,
    Cue,
    Sample,
    Capture,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Origin {
    identity: String,
    sha256: Option<String>,
}
impl Origin {
    pub fn new(identity: String, sha256: Option<String>) -> Result<Self, Error> {
        validation::text(&identity)?;
        validation::hash(sha256.as_deref())?;
        Ok(Self { identity, sha256 })
    }
    pub fn identity(&self) -> &str {
        &self.identity
    }
    pub fn sha256(&self) -> Option<&str> {
        self.sha256.as_deref()
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct Settings {
    scope: Scope,
    clock: Clock,
    position_driver: PositionDriver,
    origin: Option<Origin>,
}
impl Default for Settings {
    fn default() -> Self {
        Self {
            scope: Scope::Voice,
            clock: Clock::Seconds,
            position_driver: PositionDriver::Elapsed,
            origin: None,
        }
    }
}
impl Settings {
    pub fn new(
        scope: Scope,
        clock: Clock,
        position_driver: PositionDriver,
        origin: Option<Origin>,
    ) -> Self {
        Self {
            scope,
            clock,
            position_driver,
            origin,
        }
    }
    pub fn scope(&self) -> Scope {
        self.scope
    }
    pub fn clock(&self) -> Clock {
        self.clock
    }
    pub fn position_driver(&self) -> PositionDriver {
        self.position_driver
    }
    pub fn origin(&self) -> Option<&Origin> {
        self.origin.as_ref()
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct Marker {
    name: Identifier,
    position: Rational,
}
impl Marker {
    pub fn new(name: Identifier, position: Rational) -> Result<Self, Error> {
        if position.numerator() < 0 || position.numerator() > position.denominator() {
            return Err(invalid("marker position must be in [0,1]"));
        }
        Ok(Self { name, position })
    }
    pub fn name(&self) -> &Identifier {
        &self.name
    }
    pub fn position(&self) -> Rational {
        self.position
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Endpoint {
    Number(f64),
    Gate(bool),
}
impl Endpoint {
    pub fn value(self) -> f64 {
        match self {
            Self::Number(v) => v,
            Self::Gate(v) => {
                if v {
                    1.0
                } else {
                    0.0
                }
            }
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct Segment {
    duration: Rational,
    duration_unit: Clock,
    to: Endpoint,
    curve: f64,
}
impl Segment {
    pub fn new(
        duration: Rational,
        duration_unit: Clock,
        to: Endpoint,
        curve: f64,
    ) -> Result<Self, Error> {
        if duration.numerator() < 0 {
            return Err(invalid("segment duration must be nonnegative"));
        }
        finite(to.value())?;
        finite(curve)?;
        Ok(Self {
            duration,
            duration_unit,
            to,
            curve,
        })
    }
    pub fn duration(&self) -> Rational {
        self.duration
    }
    pub fn duration_unit(&self) -> Clock {
        self.duration_unit
    }
    pub fn to(&self) -> Endpoint {
        self.to
    }
    pub fn curve(&self) -> f64 {
        self.curve
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct ExponentialApproach {
    asymptote: f64,
    time_constant: f64,
    threshold: f64,
    transition_to: f64,
    transition_seconds: f64,
    minimum_transition_distance: f64,
    minimum_time_constant: f64,
}
impl ExponentialApproach {
    pub fn new(
        asymptote: f64,
        time_constant: f64,
        threshold: f64,
        transition_to: f64,
        transition_seconds: f64,
        minimum_transition_distance: f64,
        minimum_time_constant: f64,
    ) -> Result<Self, Error> {
        for v in [
            asymptote,
            time_constant,
            threshold,
            transition_to,
            transition_seconds,
            minimum_transition_distance,
            minimum_time_constant,
        ] {
            finite(v)?;
        }
        if threshold == asymptote
            || [
                time_constant,
                transition_seconds,
                minimum_transition_distance,
                minimum_time_constant,
            ]
            .iter()
            .any(|v| *v < 0.0)
        {
            return Err(invalid("invalid captured approach"));
        }
        Ok(Self {
            asymptote,
            time_constant,
            threshold,
            transition_to,
            transition_seconds,
            minimum_transition_distance,
            minimum_time_constant,
        })
    }
    pub fn asymptote(&self) -> f64 {
        self.asymptote
    }
    pub fn time_constant(&self) -> f64 {
        self.time_constant
    }
    pub fn threshold(&self) -> f64 {
        self.threshold
    }
    pub fn transition_to(&self) -> f64 {
        self.transition_to
    }
    pub fn transition_seconds(&self) -> f64 {
        self.transition_seconds
    }
    pub fn minimum_transition_distance(&self) -> f64 {
        self.minimum_transition_distance
    }
    pub fn minimum_time_constant(&self) -> f64 {
        self.minimum_time_constant
    }
    pub fn resolve(&self, initial: f64) -> Result<Vec<Segment>, Error> {
        finite(initial)?;
        let distance = finite(self.threshold - self.asymptote)?;
        let mut start = initial;
        let mut result = Vec::new();
        if self.time_constant != 0.0 && finite(finite(initial - self.threshold)? * distance)? > 0.0
        {
            let curve = finite(finite(distance / finite(initial - self.asymptote)?)?.ln())?;
            let seconds = finite(-self.time_constant.max(self.minimum_time_constant) * curve)?;
            result.push(Segment::new(
                duration(seconds)?,
                Clock::Seconds,
                Endpoint::Number(self.threshold),
                curve,
            )?);
            start = self.threshold;
        }
        let remaining = finite(start - self.transition_to)?.abs();
        let seconds = if remaining != 0.0 {
            finite(
                finite(self.transition_seconds * remaining)?
                    / remaining.max(self.minimum_transition_distance),
            )?
        } else {
            0.0
        };
        result.push(Segment::new(
            duration(seconds)?,
            Clock::Seconds,
            Endpoint::Number(self.transition_to),
            0.0,
        )?);
        Ok(result)
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum EnvelopeSegment {
    Definite(Segment),
    Indefinite,
    Approach(ExponentialApproach),
}
#[derive(Clone, Debug, PartialEq)]
pub enum Initial {
    Number(f64),
    Current,
}
#[derive(Clone, Debug, PartialEq)]
pub enum Rate {
    Literal(Rational),
    Parameter(Identifier),
}

#[derive(Clone, Debug, PartialEq)]
pub struct Lfo {
    shape: Waveform,
    rate: Rate,
    phase: Rational,
    duty_cycle: Rational,
    reset: Reset,
    delay: Rational,
    fade_in: Rational,
    center: f64,
    depth: f64,
    markers: Vec<Marker>,
}
impl Lfo {
    pub fn shape(&self) -> Waveform {
        self.shape
    }
    pub fn rate(&self) -> &Rate {
        &self.rate
    }
    pub fn phase(&self) -> Rational {
        self.phase
    }
    pub fn duty_cycle(&self) -> Rational {
        self.duty_cycle
    }
    pub fn reset(&self) -> Reset {
        self.reset
    }
    pub fn delay(&self) -> Rational {
        self.delay
    }
    pub fn fade_in(&self) -> Rational {
        self.fade_in
    }
    pub fn center(&self) -> f64 {
        self.center
    }
    pub fn depth(&self) -> f64 {
        self.depth
    }
    pub fn markers(&self) -> &[Marker] {
        &self.markers
    }
}
#[derive(Clone, Debug, PartialEq)]
pub struct Envelope {
    initial: Initial,
    start: Start,
    segments: Vec<EnvelopeSegment>,
    release: Vec<EnvelopeSegment>,
    polarity: Polarity,
    hold: bool,
    retrigger: Retrigger,
    playback: PlaybackMode,
    markers: Vec<Marker>,
    loop_start: Option<Identifier>,
    loop_end: Option<Identifier>,
    repeat_count: Option<i64>,
}
impl Envelope {
    pub fn initial(&self) -> &Initial {
        &self.initial
    }
    pub fn start(&self) -> Start {
        self.start
    }
    pub fn segments(&self) -> &[EnvelopeSegment] {
        &self.segments
    }
    pub fn release(&self) -> &[EnvelopeSegment] {
        &self.release
    }
    pub fn polarity(&self) -> Polarity {
        self.polarity
    }
    pub fn hold(&self) -> bool {
        self.hold
    }
    pub fn retrigger(&self) -> Retrigger {
        self.retrigger
    }
    pub fn playback(&self) -> PlaybackMode {
        self.playback
    }
    pub fn markers(&self) -> &[Marker] {
        &self.markers
    }
    pub fn loop_start(&self) -> Option<&Identifier> {
        self.loop_start.as_ref()
    }
    pub fn loop_end(&self) -> Option<&Identifier> {
        self.loop_end.as_ref()
    }
    pub fn repeat_count(&self) -> Option<i64> {
        self.repeat_count
    }
}
#[derive(Clone, Debug, PartialEq)]
pub struct SampleHold {
    minimum: f64,
    maximum: f64,
}
impl SampleHold {
    pub fn minimum(&self) -> f64 {
        self.minimum
    }
    pub fn maximum(&self) -> f64 {
        self.maximum
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct Stage {
    name: Identifier,
    envelfo: Generator,
}
impl Stage {
    pub fn name(&self) -> &Identifier {
        &self.name
    }
    pub fn envelfo(&self) -> &Generator {
        &self.envelfo
    }
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum StageAction {
    Enter { stage: Identifier },
    Finish,
}
#[derive(Clone, Debug, PartialEq)]
pub struct StageTransition {
    from_stages: Vec<Identifier>,
    event: String,
    action: StageAction,
}
impl StageTransition {
    pub fn from_stages(&self) -> &[Identifier] {
        &self.from_stages
    }
    pub fn event(&self) -> &str {
        &self.event
    }
    pub fn action(&self) -> &StageAction {
        &self.action
    }
}
#[derive(Clone, Debug, PartialEq)]
pub struct Stages {
    initial_stage: Identifier,
    stages: Vec<Stage>,
    transitions: Vec<StageTransition>,
}
impl Stages {
    pub fn initial_stage(&self) -> &Identifier {
        &self.initial_stage
    }
    pub fn stages(&self) -> &[Stage] {
        &self.stages
    }
    pub fn transitions(&self) -> &[StageTransition] {
        &self.transitions
    }
    pub fn event_ports(&self) -> Vec<String> {
        validation::stage_ports(self)
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum SignalOperation {
    Sum,
    Product,
    Affine {
        scale: f64,
        offset: f64,
    },
    Quantize {
        step: f64,
        origin: f64,
    },
    Latch,
    Threshold {
        lower: f64,
        upper: f64,
    },
    Slew {
        rise: f64,
        fall: f64,
        initial: Option<f64>,
    },
}
#[derive(Clone, Debug, PartialEq)]
pub struct SignalNode {
    inputs: Vec<Identifier>,
    operation: SignalOperation,
}
impl SignalNode {
    pub fn inputs(&self) -> &[Identifier] {
        &self.inputs
    }
    pub fn operation(&self) -> &SignalOperation {
        &self.operation
    }
}
#[derive(Clone, Debug, PartialEq)]
pub enum PatchNode {
    Generator(Box<Generator>),
    Signal(SignalNode),
}
#[derive(Clone, Debug, PartialEq)]
pub struct PatchEventConnection {
    source: String,
    target: Identifier,
    action: EventAction,
    cue: Option<Identifier>,
    every: i64,
    offset: i64,
    probability: f64,
    delay: Rational,
}
impl PatchEventConnection {
    pub fn source(&self) -> &str {
        &self.source
    }
    pub fn target(&self) -> &Identifier {
        &self.target
    }
    pub fn action(&self) -> EventAction {
        self.action
    }
    pub fn cue(&self) -> Option<&Identifier> {
        self.cue.as_ref()
    }
    pub fn every(&self) -> i64 {
        self.every
    }
    pub fn offset(&self) -> i64 {
        self.offset
    }
    pub fn probability(&self) -> f64 {
        self.probability
    }
    pub fn delay(&self) -> Rational {
        self.delay
    }
}
#[derive(Clone, Debug, PartialEq)]
pub struct Patch {
    envelfos: Vec<(Identifier, PatchNode)>,
    outputs: Vec<(Identifier, Identifier)>,
    event_outputs: Vec<(Identifier, String)>,
    events: Vec<PatchEventConnection>,
    signal_order: Vec<Identifier>,
    signal_ranges: Vec<(Identifier, (f64, f64))>,
}
impl Patch {
    pub fn envelfos(&self) -> &[(Identifier, PatchNode)] {
        &self.envelfos
    }
    pub fn outputs(&self) -> &[(Identifier, Identifier)] {
        &self.outputs
    }
    pub fn event_outputs(&self) -> &[(Identifier, String)] {
        &self.event_outputs
    }
    pub fn events(&self) -> &[PatchEventConnection] {
        &self.events
    }
    pub fn signal_order(&self) -> &[Identifier] {
        &self.signal_order
    }
    pub fn signal_ranges(&self) -> &[(Identifier, (f64, f64))] {
        &self.signal_ranges
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum ParameterValue {
    Number(f64),
    Text(String),
}
#[derive(Clone, Debug, PartialEq)]
pub struct ScoreReference {
    path: Option<String>,
    selector: Option<String>,
    sha256: Option<String>,
}
impl ScoreReference {
    pub fn path(&self) -> Option<&str> {
        self.path.as_deref()
    }
    pub fn selector(&self) -> Option<&str> {
        self.selector.as_deref()
    }
    pub fn sha256(&self) -> Option<&str> {
        self.sha256.as_deref()
    }
}
#[derive(Clone, Debug, PartialEq)]
pub struct Reference {
    score: ScoreReference,
    parameters: Vec<(Identifier, ParameterValue)>,
}
impl Reference {
    pub fn score(&self) -> &ScoreReference {
        &self.score
    }
    pub fn parameters(&self) -> &[(Identifier, ParameterValue)] {
        &self.parameters
    }
}
#[derive(Clone, Debug, PartialEq)]
pub enum Body {
    Lfo(Lfo),
    Envelope(Envelope),
    Stages(Stages),
    SampleHold(SampleHold),
    Patch(Patch),
    Reference(Reference),
}
#[derive(Clone, Debug, PartialEq)]
pub struct Generator {
    settings: Settings,
    body: Body,
}
impl Generator {
    /// Reconstruct a definition with new root settings, checking the whole tree.
    pub fn new(settings: Settings, body: Body, limits: PreparationLimits) -> Result<Self, Error> {
        let mut value = Self { settings, body };
        preparation_records(
            &serde_json::to_value(&value).map_err(|e| invalid(&e.to_string()))?,
            limits,
        )?;
        validation::generator(&mut value)?;
        Ok(value)
    }
    pub fn lfo(rate: Rate, settings: Settings, limits: PreparationLimits) -> Result<Self, Error> {
        Self::new(
            settings,
            Body::Lfo(Lfo {
                shape: Waveform::Sine,
                rate,
                phase: Rational::new(0, 1)?,
                duty_cycle: Rational::new(1, 2)?,
                reset: Reset::Trigger,
                delay: Rational::new(0, 1)?,
                fade_in: Rational::new(0, 1)?,
                center: 0.0,
                depth: 1.0,
                markers: Vec::new(),
            }),
            limits,
        )
    }
    pub fn settings(&self) -> &Settings {
        &self.settings
    }
    pub fn body(&self) -> &Body {
        &self.body
    }
    pub(crate) fn decode<'de, D: Deserializer<'de>>(
        deserializer: D,
        limits: PreparationLimits,
    ) -> Result<Self, D::Error> {
        wire::decode(deserializer, limits)
    }
}
impl<'de> Deserialize<'de> for Generator {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        Self::decode(deserializer, PreparationLimits::default())
    }
}
impl Serialize for Generator {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        wire::definition(self, false).serialize(serializer)
    }
}

pub fn quantize_value(value: f64, step: f64, origin: f64) -> Result<f64, Error> {
    finite(value)?;
    finite(step)?;
    finite(origin)?;
    if step <= 0.0 {
        return Err(invalid("quantizer step must be positive"));
    }
    let position = finite(finite(value - origin)? / step)?;
    let lower = position.floor();
    finite(origin + finite((lower + if position - lower >= 0.5 { 1.0 } else { 0.0 }) * step)?)
}

fn duration(seconds: f64) -> Result<Rational, Error> {
    let nanos = finite(seconds * 1_000_000_000.0)?.round_ties_even();
    if !(0.0..9_223_372_036_854_775_808.0).contains(&nanos) {
        return Err(Error::ArithmeticRange);
    }
    Rational::new(nanos as i64, 1_000_000_000)
}
fn invalid(message: &str) -> Error {
    Error::Invalid(message.into())
}

#[derive(Clone, Debug, PartialEq)]
pub struct EnvelfoParameter {
    unit: Unit,
    default: f64,
    minimum: f64,
    maximum: f64,
    description: Option<String>,
}
impl EnvelfoParameter {
    pub fn new(
        unit: Unit,
        default: f64,
        minimum: f64,
        maximum: f64,
        description: Option<String>,
    ) -> Result<Self, Error> {
        for v in [default, minimum, maximum] {
            finite(v)?;
        }
        if minimum < 0.0
            || minimum > default
            || default > maximum
            || (unit == Unit::Hz && minimum == 0.0)
        {
            return Err(invalid("invalid envelfo parameter domain or default"));
        }
        Ok(Self {
            unit,
            default,
            minimum,
            maximum,
            description,
        })
    }
    pub fn unit(&self) -> Unit {
        self.unit
    }
    pub fn default_value(&self) -> f64 {
        self.default
    }
    pub fn minimum(&self) -> f64 {
        self.minimum
    }
    pub fn maximum(&self) -> f64 {
        self.maximum
    }
    pub fn description(&self) -> Option<&str> {
        self.description.as_deref()
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct EnvelfoScore {
    name: String,
    title: String,
    tags: Vec<String>,
    parameters: Vec<(Identifier, EnvelfoParameter)>,
    body: Generator,
}
impl EnvelfoScore {
    pub fn new(
        name: String,
        title: String,
        tags: Vec<String>,
        parameters: Vec<(Identifier, EnvelfoParameter)>,
        body: Generator,
        limits: PreparationLimits,
    ) -> Result<Self, Error> {
        limits.check_records(parameters.len())?;
        let tags = crate::musical::header(&name, &title, tags)?;
        let declared: BTreeMap<_, _> = parameters.iter().map(|(n, p)| (n, p)).collect();
        if declared.len() != parameters.len() || matches!(body.body, Body::Reference(_)) {
            return Err(invalid("invalid score body or duplicate public parameters"));
        }
        let used = if let Body::Lfo(Lfo {
            rate: Rate::Parameter(ref p),
            ..
        }) = body.body
        {
            Some(p)
        } else {
            None
        };
        match used {
            Some(name) => {
                if parameters.len() != 1 || declared.get(name).is_none_or(|p| p.unit != Unit::Hz) {
                    return Err(invalid(
                        "LFO public rate requires exactly its declared Hz parameter",
                    ));
                }
                if body.settings.clock == Clock::Beats {
                    return Err(invalid("Hz parameters require a seconds-clock LFO"));
                }
            }
            None if !parameters.is_empty() => return Err(invalid("unused public parameters")),
            None => (),
        }
        let mut value = Self {
            name,
            title,
            tags,
            parameters,
            body,
        };
        preparation_records(
            &serde_json::to_value(&value).map_err(|e| invalid(&e.to_string()))?,
            limits,
        )?;
        validation::generator(&mut value.body)?;
        Ok(value)
    }
    pub fn name(&self) -> &str {
        &self.name
    }
    pub fn title(&self) -> &str {
        &self.title
    }
    pub fn tags(&self) -> &[String] {
        &self.tags
    }
    pub fn parameters(&self) -> &[(Identifier, EnvelfoParameter)] {
        &self.parameters
    }
    pub fn body(&self) -> &Generator {
        &self.body
    }
    pub fn instantiate(
        &self,
        values: &BTreeMap<Identifier, ParameterValue>,
        settings: Settings,
        limits: PreparationLimits,
    ) -> Result<Generator, Error> {
        let count = preparation_records(
            &serde_json::to_value(self).map_err(|e| invalid(&e.to_string()))?,
            limits,
        )?;
        limits.check_records(
            count
                .checked_add(values.len())
                .ok_or(Error::ArithmeticRange)?,
        )?;
        let declared: BTreeMap<_, _> = self.parameters.iter().map(|(n, p)| (n, p)).collect();
        if values.keys().any(|n| !declared.contains_key(n)) {
            return Err(invalid("unknown public envelfo parameter"));
        }
        let mut body = self.body.clone();
        if let Body::Lfo(lfo) = &mut body.body {
            if let Rate::Parameter(name) = &lfo.rate {
                if settings.clock == Clock::Beats {
                    return Err(invalid("Hz parameters require a seconds-clock LFO"));
                }
                let p = declared[name];
                let value = match values.get(name) {
                    None => p.default,
                    Some(ParameterValue::Number(v)) => finite(*v)?,
                    Some(ParameterValue::Text(t)) => crate::quantity::rate(t)?,
                };
                if value < p.minimum || value > p.maximum {
                    return Err(invalid("public parameter is outside its domain"));
                }
                lfo.rate = Rate::Literal(crate::quantity::exact(&value.to_string(), "ratio")?);
            }
        }
        body.settings = settings;
        inherit_children(&mut body);
        Generator::new(body.settings, body.body, limits)
    }
    pub(crate) fn decode<'de, D: Deserializer<'de>>(
        d: D,
        limits: PreparationLimits,
    ) -> Result<Self, D::Error> {
        wire::ScoreWire::deserialize(d)?
            .prepare(limits)
            .map_err(serde::de::Error::custom)
    }
}
impl Serialize for EnvelfoScore {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        wire::score_definition(self).serialize(s)
    }
}
impl<'de> Deserialize<'de> for EnvelfoScore {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        Self::decode(d, PreparationLimits::default())
    }
}

fn inherit_children(value: &mut Generator) {
    let settings = &value.settings;
    let update = |g: &mut Generator| {
        g.settings.scope = settings.scope;
        g.settings.clock = settings.clock;
        inherit_children(g);
    };
    match &mut value.body {
        Body::Stages(v) => {
            for s in &mut v.stages {
                update(&mut s.envelfo);
            }
        }
        Body::Patch(v) => {
            for (_, n) in &mut v.envelfos {
                if let PatchNode::Generator(g) = n {
                    update(g);
                }
            }
        }
        _ => (),
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PreparationLimits {
    max_records: usize,
}

impl Default for PreparationLimits {
    fn default() -> Self {
        Self {
            max_records: 10_000,
        }
    }
}

impl PreparationLimits {
    pub fn new(max_records: usize) -> Result<Self, Error> {
        if u64::try_from(max_records).map_err(|_| Error::ArithmeticRange)? > i64::MAX as u64 {
            return Err(Error::Invalid(
                "max_records exceeds the signed 64-bit domain".into(),
            ));
        }
        Ok(Self { max_records })
    }

    pub fn max_records(self) -> usize {
        self.max_records
    }

    pub fn check_records(self, count: usize) -> Result<(), Error> {
        if count > self.max_records {
            Err(Error::Limit("generator preparation records"))
        } else {
            Ok(())
        }
    }
}

/// Count declarations and references once per occurrence, without expanding
/// shared nodes. Text, parsed-value and nesting budgets are separate checks.
pub fn preparation_records(value: &Value, limits: PreparationLimits) -> Result<usize, Error> {
    let mut pending = vec![value];
    let mut count = usize::from(value.is_object());
    limits.check_records(count)?;
    while let Some(item) = pending.pop() {
        let Some(item) = item.as_object() else {
            continue;
        };
        for (key, child) in item {
            match key.as_str() {
                "envelfos" | "parameters" | "controls" if child.is_object() => {
                    count = count
                        .checked_add(child.as_object().map_or(0, |v| v.len()))
                        .ok_or(Error::ArithmeticRange)?;
                    limits.check_records(count)?;
                    pending.extend(child.as_object().into_iter().flat_map(|v| v.values()));
                }
                "segments" | "release" | "markers" | "stages" | "transitions" | "events"
                | "event_connections" | "bindings" | "sources" | "routes" | "points"
                | "parameters" | "equalizer" | "filters" | "operators" | "edges"
                    if child.is_array() =>
                {
                    count = count
                        .checked_add(child.as_array().map_or(0, Vec::len))
                        .ok_or(Error::ArithmeticRange)?;
                    limits.check_records(count)?;
                    pending.extend(child.as_array().into_iter().flatten());
                }
                "inputs" | "from" | "from_stages" if child.is_array() => {
                    count = count
                        .checked_add(child.as_array().map_or(0, Vec::len))
                        .ok_or(Error::ArithmeticRange)?;
                }
                "outputs" | "event_outputs" if child.is_object() => {
                    count = count
                        .checked_add(child.as_object().map_or(0, |v| v.len()))
                        .ok_or(Error::ArithmeticRange)?;
                }
                "body" | "envelfo" | "modulation" | "processing" | "envelope" | "tolerance"
                    if child.is_object() =>
                {
                    count = count.checked_add(1).ok_or(Error::ArithmeticRange)?;
                    limits.check_records(count)?;
                    pending.push(child);
                }
                _ => (),
            }
            limits.check_records(count)?;
        }
    }
    Ok(count)
}
