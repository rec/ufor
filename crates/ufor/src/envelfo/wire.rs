//! Authored wire records. Only Generator exposes a validated Serde boundary.
use super::*;
use crate::quantity;
use serde::de::{MapAccess, Visitor};
use serde::ser::SerializeMap;
use std::marker::PhantomData;

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct Ordered<T>(pub Vec<(Identifier, T)>);
impl<T> Default for Ordered<T> {
    fn default() -> Self {
        Self(Vec::new())
    }
}
impl<T: Serialize> Serialize for Ordered<T> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut map = serializer.serialize_map(Some(self.0.len()))?;
        for (key, value) in &self.0 {
            map.serialize_entry(key, value)?;
        }
        map.end()
    }
}
impl<'de, T: Deserialize<'de>> Deserialize<'de> for Ordered<T> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct Entries<T>(PhantomData<T>);
        impl<'de, T: Deserialize<'de>> Visitor<'de> for Entries<T> {
            type Value = Ordered<T>;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("an identifier-keyed map")
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut values: Vec<(Identifier, T)> = Vec::new();
                let mut indices: std::collections::BTreeMap<Identifier, usize> =
                    std::collections::BTreeMap::new();
                while let Some((key, value)) = map.next_entry::<Identifier, T>()? {
                    if let Some(index) = indices.get(&key) {
                        values[*index].1 = value;
                    } else {
                        indices.insert(key.clone(), values.len());
                        values.push((key, value));
                    }
                }
                Ok(Ordered(values))
            }
        }
        deserializer.deserialize_map(Entries(PhantomData))
    }
}

#[derive(Clone, Debug, Serialize)]
#[serde(transparent)]
pub(super) struct Authored<T>(Option<T>);
impl<T> Default for Authored<T> {
    fn default() -> Self {
        Self(None)
    }
}
impl<T> Authored<T> {
    fn absent(&self) -> bool {
        self.0.is_none()
    }
}
impl<'de, T: Deserialize<'de>> Deserialize<'de> for Authored<T> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        T::deserialize(deserializer).map(|v| Self(Some(v)))
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(untagged)]
pub(super) enum Exact {
    Integer(i64),
    Text(String),
}
impl Exact {
    fn value(self, unit: &str) -> Result<Rational, Error> {
        match self {
            Self::Integer(v) => Rational::new(v, 1),
            Self::Text(v) => quantity::exact(&v, unit),
        }
    }
    fn from(value: Rational) -> Self {
        Self::Text(value.to_string())
    }
}
fn zero() -> Exact {
    Exact::Integer(0)
}
fn half() -> Exact {
    Exact::Text("1/2".into())
}
fn one() -> f64 {
    1.0
}
fn negative_one() -> f64 {
    -1.0
}
fn one_integer() -> i64 {
    1
}
fn yes() -> bool {
    true
}
fn current() -> String {
    "current".into()
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginWire {
    identity: String,
    #[serde(default)]
    sha256: Option<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct MarkerWire {
    name: Identifier,
    position: Exact,
}
impl MarkerWire {
    fn prepare(self) -> Result<Marker, Error> {
        Marker::new(self.name, self.position.value("ratio")?)
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ParameterReferenceWire {
    parameter: Identifier,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(untagged)]
pub(super) enum RateWire {
    Parameter(ParameterReferenceWire),
    Literal(Exact),
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(untagged)]
pub(super) enum InitialWire {
    Number(f64),
    Current(String),
}
fn initial() -> InitialWire {
    InitialWire::Number(0.0)
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SegmentWire {
    duration: Exact,
    to: Endpoint,
    #[serde(default)]
    curve: f64,
    #[serde(default, skip_serializing_if = "Authored::absent")]
    duration_unit: Authored<Clock>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct HoldWire {
    #[serde(default)]
    duration: Option<()>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(untagged)]
pub(super) enum Scalar {
    Number(f64),
    Text(String),
}
impl Scalar {
    fn value(self, unit: &str) -> Result<f64, Error> {
        match self {
            Self::Number(v) => finite(v),
            Self::Text(v) => {
                if unit == "per_second" {
                    quantity::rate(&v)
                } else {
                    quantity::scalar(&v, unit)
                }
            }
        }
    }
}
fn scalar_zero() -> Scalar {
    Scalar::Number(0.0)
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ApproachWire {
    #[serde(default = "approach_kind")]
    kind: String,
    asymptote: f64,
    time_constant: Scalar,
    threshold: f64,
    transition_to: f64,
    transition_seconds: Scalar,
    #[serde(default)]
    minimum_transition_distance: f64,
    #[serde(default = "scalar_zero")]
    minimum_time_constant: Scalar,
}
fn approach_kind() -> String {
    "exponential_approach".into()
}
impl ApproachWire {
    fn prepare(self) -> Result<ExponentialApproach, Error> {
        if self.kind != "exponential_approach" {
            return Err(invalid("unknown segment kind"));
        }
        ExponentialApproach::new(
            self.asymptote,
            self.time_constant.value("seconds")?,
            self.threshold,
            self.transition_to,
            self.transition_seconds.value("seconds")?,
            self.minimum_transition_distance,
            self.minimum_time_constant.value("seconds")?,
        )
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(untagged)]
pub(super) enum PartWire {
    Definite(SegmentWire),
    Approach(ApproachWire),
    Hold(HoldWire),
}
impl PartWire {
    fn prepare(self) -> Result<EnvelopeSegment, Error> {
        Ok(match self {
            Self::Definite(v) => EnvelopeSegment::Definite(v.prepare()?),
            Self::Approach(v) => EnvelopeSegment::Approach(v.prepare()?),
            Self::Hold(_) => EnvelopeSegment::Indefinite,
        })
    }
}
impl SegmentWire {
    fn prepare(self) -> Result<Segment, Error> {
        let (duration, inferred) = match self.duration {
            Exact::Integer(n) => (
                Rational::new(n, 1)?,
                self.duration_unit.0.unwrap_or(Clock::Seconds),
            ),
            Exact::Text(t) => {
                let (n, unit) = quantity::duration(&t)?;
                let unit = if unit == "beats" {
                    Clock::Beats
                } else {
                    Clock::Seconds
                };
                if self.duration_unit.0.is_some_and(|u| u != unit) {
                    return Err(invalid("conflicting segment units"));
                }
                (n, unit)
            }
        };
        Segment::new(duration, inferred, self.to, self.curve)
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct StageWire {
    name: Identifier,
    envelfo: Raw,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct TransitionWire {
    #[serde(rename = "from", alias = "from_stages")]
    from_stages: Vec<Identifier>,
    event: String,
    action: StageAction,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ConnectionWire {
    source: String,
    target: Identifier,
    #[serde(default)]
    action: EventAction,
    #[serde(default)]
    cue: Option<Identifier>,
    #[serde(default = "one_integer")]
    every: i64,
    #[serde(default)]
    offset: i64,
    #[serde(default = "one")]
    probability: f64,
    #[serde(default = "zero")]
    delay: Exact,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ReferenceWire {
    #[serde(default)]
    path: Option<String>,
    #[serde(default)]
    selector: Option<String>,
    #[serde(default)]
    sha256: Option<String>,
}

impl TryFrom<ReferenceWire> for ScoreReference {
    type Error = Error;

    fn try_from(value: ReferenceWire) -> Result<Self, Error> {
        let score = Self {
            path: value.path,
            selector: value
                .selector
                .as_deref()
                .map(validation::selector)
                .transpose()?,
            sha256: value.sha256,
        };
        validation::score_reference(&score)?;
        Ok(score)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum Raw {
    Lfo {
        #[serde(default, skip_serializing_if = "Authored::absent")]
        scope: Authored<Scope>,
        #[serde(default, skip_serializing_if = "Authored::absent")]
        clock: Authored<Clock>,
        #[serde(default, skip_serializing_if = "Authored::absent")]
        position_driver: Authored<PositionDriver>,
        #[serde(default, skip_serializing_if = "Authored::absent")]
        origin: Authored<Option<OriginWire>>,
        #[serde(default)]
        shape: Waveform,
        rate: RateWire,
        #[serde(default = "zero")]
        phase: Exact,
        #[serde(default = "half")]
        duty_cycle: Exact,
        #[serde(default)]
        reset: Reset,
        #[serde(default = "zero")]
        delay: Exact,
        #[serde(default = "zero")]
        fade_in: Exact,
        #[serde(default)]
        center: f64,
        #[serde(default = "one")]
        depth: f64,
        #[serde(default)]
        markers: Vec<MarkerWire>,
    },
    Envelope {
        #[serde(default, skip_serializing_if = "Authored::absent")]
        scope: Authored<Scope>,
        #[serde(default, skip_serializing_if = "Authored::absent")]
        clock: Authored<Clock>,
        #[serde(default, skip_serializing_if = "Authored::absent")]
        position_driver: Authored<PositionDriver>,
        #[serde(default, skip_serializing_if = "Authored::absent")]
        origin: Authored<Option<OriginWire>>,
        #[serde(default = "initial")]
        initial: InitialWire,
        #[serde(default)]
        start: Start,
        segments: Vec<PartWire>,
        #[serde(default)]
        release: Vec<PartWire>,
        #[serde(default)]
        polarity: Polarity,
        #[serde(default = "yes")]
        hold: bool,
        #[serde(default)]
        retrigger: Retrigger,
        #[serde(default)]
        playback: PlaybackMode,
        #[serde(default)]
        markers: Vec<MarkerWire>,
        #[serde(default)]
        loop_start: Option<Identifier>,
        #[serde(default)]
        loop_end: Option<Identifier>,
        #[serde(default)]
        repeat_count: Option<i64>,
    },
    Stages {
        #[serde(default, skip_serializing_if = "Authored::absent")]
        scope: Authored<Scope>,
        #[serde(default, skip_serializing_if = "Authored::absent")]
        clock: Authored<Clock>,
        #[serde(default, skip_serializing_if = "Authored::absent")]
        position_driver: Authored<PositionDriver>,
        #[serde(default, skip_serializing_if = "Authored::absent")]
        origin: Authored<Option<OriginWire>>,
        initial_stage: Identifier,
        stages: Vec<StageWire>,
        #[serde(default)]
        transitions: Vec<TransitionWire>,
    },
    SampleHold {
        #[serde(default, skip_serializing_if = "Authored::absent")]
        scope: Authored<Scope>,
        #[serde(default, skip_serializing_if = "Authored::absent")]
        clock: Authored<Clock>,
        #[serde(default, skip_serializing_if = "Authored::absent")]
        position_driver: Authored<PositionDriver>,
        #[serde(default, skip_serializing_if = "Authored::absent")]
        origin: Authored<Option<OriginWire>>,
        #[serde(default = "negative_one")]
        minimum: f64,
        #[serde(default = "one")]
        maximum: f64,
    },
    Patch {
        #[serde(default, skip_serializing_if = "Authored::absent")]
        scope: Authored<Scope>,
        #[serde(default, skip_serializing_if = "Authored::absent")]
        clock: Authored<Clock>,
        #[serde(default, skip_serializing_if = "Authored::absent")]
        position_driver: Authored<PositionDriver>,
        #[serde(default, skip_serializing_if = "Authored::absent")]
        origin: Authored<Option<OriginWire>>,
        envelfos: Ordered<Raw>,
        outputs: Ordered<Identifier>,
        #[serde(default)]
        event_outputs: Ordered<String>,
        #[serde(default)]
        events: Vec<ConnectionWire>,
    },
    Reference {
        #[serde(default, skip_serializing_if = "Authored::absent")]
        scope: Authored<Scope>,
        #[serde(default, skip_serializing_if = "Authored::absent")]
        clock: Authored<Clock>,
        #[serde(default, skip_serializing_if = "Authored::absent")]
        position_driver: Authored<PositionDriver>,
        #[serde(default, skip_serializing_if = "Authored::absent")]
        origin: Authored<Option<OriginWire>>,
        score: ScoreReference,
        #[serde(default)]
        parameters: Ordered<ParameterValue>,
    },
    Sum {
        inputs: Vec<Identifier>,
    },
    Product {
        inputs: Vec<Identifier>,
    },
    Affine {
        input: Identifier,
        #[serde(default = "one")]
        scale: f64,
        #[serde(default)]
        offset: f64,
    },
    Quantize {
        input: Identifier,
        step: f64,
        #[serde(default)]
        origin: f64,
    },
    Latch {
        input: Identifier,
    },
    Threshold {
        input: Identifier,
        lower: f64,
        upper: f64,
    },
    Slew {
        input: Identifier,
        rise: Scalar,
        fall: Scalar,
        #[serde(default)]
        initial: Option<f64>,
    },
}

fn settings(
    scope: Authored<Scope>,
    clock: Authored<Clock>,
    driver: Authored<PositionDriver>,
    origin: Authored<Option<OriginWire>>,
    parent: Option<&Settings>,
) -> Result<Settings, Error> {
    if let Some(parent) = parent {
        if scope.0.is_some() || clock.0.is_some() || driver.0.is_some() || origin.0.is_some() {
            return Err(invalid("child generators inherit common settings"));
        }
        return Ok(Settings::new(
            parent.scope,
            parent.clock,
            PositionDriver::Elapsed,
            None,
        ));
    }
    Ok(Settings::new(
        scope.0.unwrap_or(Scope::Voice),
        clock.0.unwrap_or_default(),
        driver.0.unwrap_or_default(),
        origin
            .0
            .flatten()
            .map(|o| Origin::new(o.identity, o.sha256))
            .transpose()?,
    ))
}
impl Raw {
    fn prepare(self, parent: Option<&Settings>) -> Result<Generator, Error> {
        let (settings, body) = match self {
            Self::Lfo {
                scope,
                clock,
                position_driver,
                origin,
                shape,
                rate,
                phase,
                duty_cycle,
                reset,
                delay,
                fade_in,
                center,
                depth,
                markers,
            } => {
                let s = settings(scope, clock, position_driver, origin, parent)?;
                let rate = match rate {
                    RateWire::Parameter(p) => Rate::Parameter(p.parameter),
                    RateWire::Literal(v) => Rate::Literal(v.value(if s.clock == Clock::Beats {
                        "per_beat"
                    } else {
                        "hz"
                    })?),
                };
                let clock_unit = if s.clock == Clock::Beats {
                    "beats"
                } else {
                    "seconds"
                };
                let body = Lfo {
                    shape,
                    rate,
                    phase: phase.value("phase")?,
                    duty_cycle: duty_cycle.value("ratio")?,
                    reset,
                    delay: delay.value(clock_unit)?,
                    fade_in: fade_in.value(clock_unit)?,
                    center,
                    depth,
                    markers: markers
                        .into_iter()
                        .map(MarkerWire::prepare)
                        .collect::<Result<_, _>>()?,
                };
                (s, Body::Lfo(body))
            }
            Self::Envelope {
                scope,
                clock,
                position_driver,
                origin,
                initial,
                start,
                segments,
                release,
                polarity,
                hold,
                retrigger,
                playback,
                markers,
                loop_start,
                loop_end,
                repeat_count,
            } => {
                let initial = match initial {
                    InitialWire::Number(v) => Initial::Number(v),
                    InitialWire::Current(v) if v == "current" => Initial::Current,
                    _ => return Err(invalid("unknown envelope initial")),
                };
                (
                    settings(scope, clock, position_driver, origin, parent)?,
                    Body::Envelope(Envelope {
                        initial,
                        start,
                        segments: segments
                            .into_iter()
                            .map(PartWire::prepare)
                            .collect::<Result<_, _>>()?,
                        release: release
                            .into_iter()
                            .map(PartWire::prepare)
                            .collect::<Result<_, _>>()?,
                        polarity,
                        hold,
                        retrigger,
                        playback,
                        markers: markers
                            .into_iter()
                            .map(MarkerWire::prepare)
                            .collect::<Result<_, _>>()?,
                        loop_start,
                        loop_end,
                        repeat_count,
                    }),
                )
            }
            Self::SampleHold {
                scope,
                clock,
                position_driver,
                origin,
                minimum,
                maximum,
            } => (
                settings(scope, clock, position_driver, origin, parent)?,
                Body::SampleHold(SampleHold { minimum, maximum }),
            ),
            Self::Stages {
                scope,
                clock,
                position_driver,
                origin,
                initial_stage,
                stages,
                transitions,
            } => {
                let s = settings(scope, clock, position_driver, origin, parent)?;
                let mut children = Vec::new();
                for stage in stages {
                    if !matches!(stage.envelfo, Self::Lfo { .. } | Self::Envelope { .. }) {
                        return Err(invalid("stage children must be LFO or Envelope"));
                    }
                    children.push(Stage {
                        name: stage.name,
                        envelfo: stage.envelfo.prepare(Some(&s))?,
                    });
                }
                (
                    s,
                    Body::Stages(Stages {
                        initial_stage,
                        stages: children,
                        transitions: transitions
                            .into_iter()
                            .map(|t| StageTransition {
                                from_stages: t.from_stages,
                                event: t.event,
                                action: t.action,
                            })
                            .collect(),
                    }),
                )
            }
            Self::Patch {
                scope,
                clock,
                position_driver,
                origin,
                envelfos,
                outputs,
                event_outputs,
                events,
            } => {
                let s = settings(scope, clock, position_driver, origin, parent)?;
                let mut children = Vec::new();
                for (name, node) in envelfos.0 {
                    children.push((name, node.node(&s)?));
                }
                let events = events
                    .into_iter()
                    .map(|v| {
                        Ok(PatchEventConnection {
                            source: v.source,
                            target: v.target,
                            action: v.action,
                            cue: v.cue,
                            every: v.every,
                            offset: v.offset,
                            probability: v.probability,
                            delay: v.delay.value("seconds")?,
                        })
                    })
                    .collect::<Result<_, Error>>()?;
                (
                    s,
                    Body::Patch(Patch {
                        envelfos: children,
                        outputs: outputs.0,
                        event_outputs: event_outputs.0,
                        events,
                        signal_order: Vec::new(),
                        signal_ranges: Vec::new(),
                    }),
                )
            }
            Self::Reference {
                scope,
                clock,
                position_driver,
                origin,
                score,
                parameters,
            } => (
                settings(scope, clock, position_driver, origin, parent)?,
                Body::Reference(Reference {
                    score,
                    parameters: parameters.0,
                }),
            ),
            _ => return Err(invalid("expected a concrete generator")),
        };
        Ok(Generator { settings, body })
    }
    fn node(self, parent: &Settings) -> Result<PatchNode, Error> {
        let (inputs, operation) = match self {
            Self::Sum { inputs } => (inputs, SignalOperation::Sum),
            Self::Product { inputs } => (inputs, SignalOperation::Product),
            Self::Affine {
                input,
                scale,
                offset,
            } => (vec![input], SignalOperation::Affine { scale, offset }),
            Self::Quantize {
                input,
                step,
                origin,
            } => (vec![input], SignalOperation::Quantize { step, origin }),
            Self::Latch { input } => (vec![input], SignalOperation::Latch),
            Self::Threshold {
                input,
                lower,
                upper,
            } => (vec![input], SignalOperation::Threshold { lower, upper }),
            Self::Slew {
                input,
                rise,
                fall,
                initial,
            } => (
                vec![input],
                SignalOperation::Slew {
                    rise: rise.value("per_second")?,
                    fall: fall.value("per_second")?,
                    initial,
                },
            ),
            Self::Patch { .. } | Self::Reference { .. } => {
                return Err(invalid("unsupported Patch child kind"));
            }
            other => return Ok(PatchNode::Generator(Box::new(other.prepare(Some(parent))?))),
        };
        Ok(PatchNode::Signal(SignalNode { inputs, operation }))
    }
}

pub(super) fn decode<'de, D: Deserializer<'de>>(
    deserializer: D,
    limits: PreparationLimits,
) -> Result<Generator, D::Error> {
    let raw = Raw::deserialize(deserializer)?;
    let data = serde_json::to_value(&raw).map_err(serde::de::Error::custom)?;
    preparation_records(&data, limits).map_err(serde::de::Error::custom)?;
    prepare_root(raw).map_err(serde::de::Error::custom)
}

fn prepare_root(raw: Raw) -> Result<Generator, Error> {
    let mut value = raw.prepare(None)?;
    validation::generator(&mut value)?;
    Ok(value)
}

#[derive(Serialize, Deserialize)]
#[serde(transparent)]
pub(crate) struct RootWire(Raw);

impl RootWire {
    pub(crate) fn prepare(self) -> Result<Generator, Error> {
        prepare_root(self.0)
    }

    pub(crate) fn envelope(mut value: Value) -> Result<Generator, Error> {
        if let Some(fields) = value.as_object_mut() {
            fields
                .entry("kind")
                .or_insert_with(|| Value::String("envelope".into()));
        }
        let value: Self =
            serde_json::from_value(value).map_err(|error| invalid(&error.to_string()))?;
        let generator = value.prepare()?;
        if !matches!(generator.body(), Body::Envelope(_)) {
            return Err(invalid("expected Envelope"));
        }
        Ok(generator)
    }
}

fn markers(values: &[Marker]) -> Vec<MarkerWire> {
    values
        .iter()
        .map(|v| MarkerWire {
            name: v.name.clone(),
            position: Exact::from(v.position),
        })
        .collect()
}
fn part(value: &EnvelopeSegment) -> PartWire {
    match value {
        EnvelopeSegment::Indefinite => PartWire::Hold(HoldWire { duration: None }),
        EnvelopeSegment::Definite(v) => PartWire::Definite(SegmentWire {
            duration: Exact::Text(format!(
                "{} {}",
                v.duration,
                if v.duration_unit == Clock::Beats {
                    "beat"
                } else {
                    "s"
                }
            )),
            to: v.to,
            curve: v.curve,
            duration_unit: Authored(None),
        }),
        EnvelopeSegment::Approach(v) => PartWire::Approach(ApproachWire {
            kind: approach_kind(),
            asymptote: v.asymptote,
            time_constant: Scalar::Number(v.time_constant),
            threshold: v.threshold,
            transition_to: v.transition_to,
            transition_seconds: Scalar::Number(v.transition_seconds),
            minimum_transition_distance: v.minimum_transition_distance,
            minimum_time_constant: Scalar::Number(v.minimum_time_constant),
        }),
    }
}

impl Serialize for Segment {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        part(&EnvelopeSegment::Definite(self.clone())).serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for Segment {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        SegmentWire::deserialize(deserializer)?
            .prepare()
            .map_err(serde::de::Error::custom)
    }
}
impl Serialize for ExponentialApproach {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        part(&EnvelopeSegment::Approach(self.clone())).serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for ExponentialApproach {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        ApproachWire::deserialize(deserializer)?
            .prepare()
            .map_err(serde::de::Error::custom)
    }
}
fn node(value: &PatchNode) -> Raw {
    match value {
        PatchNode::Generator(v) => definition(v, true),
        PatchNode::Signal(v) => match v.operation {
            SignalOperation::Sum => Raw::Sum {
                inputs: v.inputs.clone(),
            },
            SignalOperation::Product => Raw::Product {
                inputs: v.inputs.clone(),
            },
            SignalOperation::Affine { scale, offset } => Raw::Affine {
                input: v.inputs[0].clone(),
                scale,
                offset,
            },
            SignalOperation::Quantize { step, origin } => Raw::Quantize {
                input: v.inputs[0].clone(),
                step,
                origin,
            },
            SignalOperation::Latch => Raw::Latch {
                input: v.inputs[0].clone(),
            },
            SignalOperation::Threshold { lower, upper } => Raw::Threshold {
                input: v.inputs[0].clone(),
                lower,
                upper,
            },
            SignalOperation::Slew {
                rise,
                fall,
                initial,
            } => Raw::Slew {
                input: v.inputs[0].clone(),
                rise: Scalar::Number(rise),
                fall: Scalar::Number(fall),
                initial,
            },
        },
    }
}
pub(super) fn definition(value: &Generator, inherited: bool) -> Raw {
    let s = &value.settings;
    let scope = Authored((!inherited).then_some(s.scope));
    let clock = Authored((!inherited).then_some(s.clock));
    let position_driver = Authored((!inherited).then_some(s.position_driver));
    let origin = Authored((!inherited).then(|| {
        s.origin.as_ref().map(|v| OriginWire {
            identity: v.identity.clone(),
            sha256: v.sha256.clone(),
        })
    }));
    match &value.body {
        Body::Lfo(v) => Raw::Lfo {
            scope,
            clock,
            position_driver,
            origin,
            shape: v.shape,
            rate: match &v.rate {
                Rate::Literal(n) => RateWire::Literal(Exact::from(*n)),
                Rate::Parameter(p) => RateWire::Parameter(ParameterReferenceWire {
                    parameter: p.clone(),
                }),
            },
            phase: Exact::from(v.phase),
            duty_cycle: Exact::from(v.duty_cycle),
            reset: v.reset,
            delay: Exact::from(v.delay),
            fade_in: Exact::from(v.fade_in),
            center: v.center,
            depth: v.depth,
            markers: markers(&v.markers),
        },
        Body::Envelope(v) => Raw::Envelope {
            scope,
            clock,
            position_driver,
            origin,
            initial: match v.initial {
                Initial::Current => InitialWire::Current(current()),
                Initial::Number(n) => InitialWire::Number(n),
            },
            start: v.start,
            segments: v.segments.iter().map(part).collect(),
            release: v.release.iter().map(part).collect(),
            polarity: v.polarity,
            hold: v.hold,
            retrigger: v.retrigger,
            playback: v.playback,
            markers: markers(&v.markers),
            loop_start: v.loop_start.clone(),
            loop_end: v.loop_end.clone(),
            repeat_count: v.repeat_count,
        },
        Body::SampleHold(v) => Raw::SampleHold {
            scope,
            clock,
            position_driver,
            origin,
            minimum: v.minimum,
            maximum: v.maximum,
        },
        Body::Stages(v) => Raw::Stages {
            scope,
            clock,
            position_driver,
            origin,
            initial_stage: v.initial_stage.clone(),
            stages: v
                .stages
                .iter()
                .map(|s| StageWire {
                    name: s.name.clone(),
                    envelfo: definition(&s.envelfo, true),
                })
                .collect(),
            transitions: v
                .transitions
                .iter()
                .map(|t| TransitionWire {
                    from_stages: t.from_stages.clone(),
                    event: t.event.clone(),
                    action: t.action.clone(),
                })
                .collect(),
        },
        Body::Patch(v) => Raw::Patch {
            scope,
            clock,
            position_driver,
            origin,
            envelfos: Ordered(
                v.envelfos
                    .iter()
                    .map(|(n, v)| (n.clone(), node(v)))
                    .collect(),
            ),
            outputs: Ordered(v.outputs.clone()),
            event_outputs: Ordered(v.event_outputs.clone()),
            events: v
                .events
                .iter()
                .map(|v| ConnectionWire {
                    source: v.source.clone(),
                    target: v.target.clone(),
                    action: v.action,
                    cue: v.cue.clone(),
                    every: v.every,
                    offset: v.offset,
                    probability: v.probability,
                    delay: Exact::from(v.delay),
                })
                .collect(),
        },
        Body::Reference(v) => Raw::Reference {
            scope,
            clock,
            position_driver,
            origin,
            score: v.score.clone(),
            parameters: Ordered(v.parameters.clone()),
        },
    }
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ParameterWire {
    unit: Unit,
    default: Scalar,
    minimum: Scalar,
    maximum: Scalar,
    #[serde(default)]
    description: Option<String>,
}
impl ParameterWire {
    fn prepare(self) -> Result<EnvelfoParameter, Error> {
        let unit = if self.unit == Unit::Hz {
            "per_second"
        } else {
            self.unit.as_str()
        };
        EnvelfoParameter::new(
            self.unit,
            self.default.value(unit)?,
            self.minimum.value(unit)?,
            self.maximum.value(unit)?,
            self.description,
        )
    }
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ScoreWire {
    #[serde(default = "score_format")]
    format: String,
    #[serde(default = "score_version")]
    version: i64,
    #[serde(default = "score_kind")]
    kind: String,
    name: String,
    title: String,
    #[serde(default)]
    tags: Vec<String>,
    #[serde(default)]
    parameters: Ordered<ParameterWire>,
    body: Raw,
}
fn score_format() -> String {
    "recs".into()
}
fn score_version() -> i64 {
    4
}
fn score_kind() -> String {
    "envelfo".into()
}
impl ScoreWire {
    pub(crate) fn prepare(self, limits: PreparationLimits) -> Result<EnvelfoScore, Error> {
        if self.format != "recs" || self.version != 4 || self.kind != "envelfo" {
            return Err(invalid("expected a recs version 4 envelfo score"));
        }
        preparation_records(
            &serde_json::to_value(&self).map_err(|e| invalid(&e.to_string()))?,
            limits,
        )?;
        let parameters = self
            .parameters
            .0
            .into_iter()
            .map(|(n, p)| Ok((n, p.prepare()?)))
            .collect::<Result<_, Error>>()?;
        EnvelfoScore::new(
            self.name,
            self.title,
            self.tags,
            parameters,
            self.body.prepare(None)?,
            limits,
        )
    }
}
pub(super) fn score_definition(value: &EnvelfoScore) -> ScoreWire {
    ScoreWire {
        format: score_format(),
        version: score_version(),
        kind: score_kind(),
        name: value.name.clone(),
        title: value.title.clone(),
        tags: value.tags.clone(),
        parameters: Ordered(
            value
                .parameters
                .iter()
                .map(|(n, p)| {
                    (
                        n.clone(),
                        ParameterWire {
                            unit: p.unit,
                            default: Scalar::Number(p.default),
                            minimum: Scalar::Number(p.minimum),
                            maximum: Scalar::Number(p.maximum),
                            description: p.description.clone(),
                        },
                    )
                })
                .collect(),
        ),
        body: definition(&value.body, false),
    }
}
