//! Effect connections, named layouts, and latency alignment.
use super::{Definition, Processor};
use crate::envelfo::PreparationLimits;
use crate::error::Error;
use crate::identifier::Identifier;
use crate::modulation::Modulation;
use crate::samples::processing::Binding;
use serde::Deserialize;
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};

/// Effect graph topology and its deterministic, dependency-layered order.
#[derive(Debug)]
pub struct Topology {
    pub(super) processors: BTreeMap<Identifier, Processor>,
    pub(super) inputs: BTreeSet<Identifier>,
    dependencies: BTreeMap<Identifier, BTreeSet<Identifier>>,
    order: Vec<Identifier>,
    layouts: BTreeMap<Identifier, Vec<Identifier>>,
    output_channels: Vec<Identifier>,
}

impl Topology {
    pub fn decode(value: Value, limits: PreparationLimits) -> Result<Self, Error> {
        crate::envelfo::preparation_records(&value, limits)?;
        let body: Body =
            serde_json::from_value(value).map_err(|error| invalid(error.to_string()))?;
        let modulation = match body.modulation {
            Some(value) => Modulation::decode(value, limits.max_records())
                .map_err(|error| invalid(error.to_string()))?,
            None => Modulation::default(),
        };
        if matches!(body.scope, Scope::Voice | Scope::Master) != body.owner.is_none() {
            return Err(invalid(
                "voice/master graphs omit owner; instrument/host require it",
            ));
        }
        let mut inputs = BTreeMap::new();
        let mut main = 0;
        for input in body.inputs {
            super::check_names(&input.channels)?;
            if matches!(input.source, Stream::Main) {
                main += 1;
            } else if body.scope == Scope::Voice {
                return Err(invalid(
                    "per-voice graphs can only consume their own main stream",
                ));
            }
            if inputs.insert(input.name, input.channels).is_some() {
                return Err(invalid("duplicate effect graph input"));
            }
        }
        if main != 1 {
            return Err(invalid("effect graph requires exactly one main input"));
        }
        let mut processors = BTreeMap::new();
        for processor in body.processors {
            if processors
                .insert(processor.name().clone(), processor)
                .is_some()
            {
                return Err(invalid("duplicate effect processor"));
            }
        }
        if processors.is_empty() {
            return Err(invalid("effect graph requires at least one processor"));
        }
        let mut dependencies: BTreeMap<_, BTreeSet<_>> = processors
            .keys()
            .map(|name| (name.clone(), BTreeSet::new()))
            .collect();
        let mut connections: BTreeMap<_, BTreeMap<_, _>> = processors
            .keys()
            .map(|name| (name.clone(), BTreeMap::new()))
            .collect();
        for connection in body.connections {
            let name = &connection.processor;
            let ports = connections
                .get_mut(name)
                .ok_or_else(|| invalid("unknown destination processor"))?;
            match &connection.source {
                Source::Processor { processor } => {
                    check_audio_processor(&processors, processor)?;
                    dependencies
                        .get_mut(name)
                        .expect("known processor")
                        .insert(processor.clone());
                }
                Source::Input { input } if !inputs.contains_key(input) => {
                    return Err(invalid("unknown graph input"));
                }
                Source::Input { .. } => (),
            }
            if ports.insert(connection.port, connection.source).is_some() {
                return Err(invalid("duplicate processor input connection"));
            }
        }
        for (name, processor) in &processors {
            let connected = &connections[name];
            let required = processor_ports(processor);
            if required.len() != connected.len()
                || !connected
                    .keys()
                    .all(|port| required.contains(&port.as_str()))
            {
                return Err(invalid(format!(
                    "effect processor {} requires its declared ports",
                    name.as_str()
                )));
            }
        }
        let sources: BTreeSet<_> = modulation
            .sources()
            .iter()
            .map(|source| source.name())
            .collect();
        let mut bound = BTreeSet::new();
        let mut followers = BTreeMap::new();
        for binding in &body.bindings {
            if !bound.insert(binding.name()) || !sources.contains(binding.name()) {
                return Err(invalid("duplicate or unknown effect modulation binding"));
            }
            match binding {
                Binding::Follower(binding) => {
                    if !processors
                        .get(binding.processor())
                        .is_some_and(|p| matches!(p.0, Definition::Follower { .. }))
                    {
                        return Err(invalid("follower binding requires a follower processor"));
                    }
                    followers.insert(binding.name(), binding.processor());
                }
                Binding::Generator(_) => (),
                _ => {
                    return Err(invalid(
                        "effect modulation requires Envelfo or follower bindings",
                    ));
                }
            }
        }
        if bound != sources {
            return Err(invalid("each effect modulation source requires a binding"));
        }
        for route in modulation.routes() {
            let prerequisites = dependencies
                .get_mut(route.target().name())
                .ok_or_else(|| invalid("unknown effect modulation target processor"))?;
            if let Some(&follower) = followers.get(route.source()) {
                prerequisites.insert(follower.clone());
            }
        }
        let order = layered_order(&dependencies)?;
        let Source::Processor { processor: output } = body.output else {
            return Err(invalid(
                "every processor must contribute to the graph output",
            ));
        };
        check_audio_processor(&processors, &output)?;
        let mut pending = vec![&output];
        let mut used = BTreeSet::new();
        while let Some(node) = pending.pop() {
            if used.insert(node) {
                pending.extend(&dependencies[node]);
            }
        }
        if used.len() != processors.len() {
            return Err(invalid(
                "every processor must contribute to the graph output",
            ));
        }
        let mut layouts = BTreeMap::<_, Vec<Identifier>>::new();
        for name in &order {
            let ports = connections[name]
                .iter()
                .map(|(port, source)| {
                    let channels = match source {
                        Source::Input { input } => inputs[input].as_slice(),
                        Source::Processor { processor } => layouts[processor].as_slice(),
                    };
                    (port.as_str(), channels)
                })
                .collect();
            layouts.insert(name.clone(), processor_layout(&processors[name], &ports)?);
        }
        let output_channels = layouts[&output].clone();
        Ok(Self {
            processors,
            inputs: inputs.into_keys().collect(),
            dependencies,
            order,
            layouts,
            output_channels,
        })
    }

    pub fn order(&self) -> &[Identifier] {
        &self.order
    }

    pub fn layouts(&self) -> &BTreeMap<Identifier, Vec<Identifier>> {
        &self.layouts
    }

    pub fn output_channels(&self) -> &[Identifier] {
        &self.output_channels
    }

    /// Arrival plus intrinsic latency for each processor at a host sample rate.
    pub fn latencies(&self, sample_rate: i64) -> Result<BTreeMap<Identifier, i64>, Error> {
        if sample_rate <= 0 {
            return Err(invalid("effect sample rate must be positive"));
        }
        let mut result = BTreeMap::<_, i64>::new();
        for name in &self.order {
            let arrival = self.dependencies[name]
                .iter()
                .map(|node| result[node])
                .max()
                .unwrap_or(0);
            let latency = match &self.processors[name].0 {
                Definition::Limiter {
                    lookahead_seconds, ..
                } => {
                    let frames = (lookahead_seconds * sample_rate as f64).ceil();
                    if frames >= -(i64::MIN as f64) {
                        return Err(Error::ArithmeticRange);
                    }
                    frames as i64
                }
                Definition::Waveshaper { .. } => 48,
                Definition::FrequencyShifter { .. } => 512,
                Definition::Convolution {
                    partition_frames, ..
                } => *partition_frames,
                _ => 0,
            };
            result.insert(
                name.clone(),
                arrival.checked_add(latency).ok_or(Error::ArithmeticRange)?,
            );
        }
        Ok(result)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Body {
    scope: Scope,
    #[serde(default)]
    owner: Option<Identifier>,
    inputs: Vec<Input>,
    processors: Vec<Processor>,
    connections: Vec<Connection>,
    output: Source,
    #[serde(default)]
    modulation: Option<Value>,
    #[serde(default)]
    bindings: Vec<Binding>,
}

#[derive(Clone, Copy, PartialEq, Deserialize)]
#[serde(rename_all = "snake_case")]
enum Scope {
    Voice,
    Instrument,
    Master,
    Host,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    name: Identifier,
    channels: Vec<Identifier>,
    source: Stream,
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Stream {
    Main,
    Host {
        #[serde(rename = "stream")]
        _stream: Identifier,
    },
    Instrument {
        #[serde(rename = "instrument")]
        _instrument: Identifier,
        #[serde(rename = "tap")]
        _tap: InstrumentTap,
    },
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum InstrumentTap {
    PreEffect,
    PostEffect,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Connection {
    processor: Identifier,
    port: Identifier,
    source: Source,
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Source {
    Input { input: Identifier },
    Processor { processor: Identifier },
}

fn processor_ports(processor: &Processor) -> Vec<&str> {
    match &processor.0 {
        Definition::Mixer { inputs, .. } => inputs.iter().map(|port| port.name.as_str()).collect(),
        Definition::Crossfader { .. } => vec!["first", "second"],
        Definition::Compressor { .. } | Definition::Gate { .. } | Definition::Expander { .. } => {
            vec!["input", "detector"]
        }
        Definition::Multiply { .. } => vec!["carrier", "modulator"],
        _ => vec!["input"],
    }
}

fn processor_layout(
    processor: &Processor,
    ports: &BTreeMap<&str, &[Identifier]>,
) -> Result<Vec<Identifier>, Error> {
    let output = match &processor.0 {
        Definition::Follower { .. } => return names(["level"]),
        Definition::Mixer { inputs, .. } => {
            let layout = ports[inputs[0].name.as_str()];
            if ports.values().any(|&channels| channels != layout) {
                return Err(invalid(
                    "mixer and crossfader inputs require matching named layouts",
                ));
            }
            layout
        }
        Definition::Crossfader { .. } | Definition::Multiply { .. } => {
            let mut layouts = ports.values();
            let first = *layouts.next().expect("checked ports");
            if layouts.any(|&layout| layout != first) {
                return Err(invalid("processor inputs require matching named layouts"));
            }
            first
        }
        Definition::Matrix {
            input_channels,
            output_channels,
            ..
        }
        | Definition::Convolution {
            input_channels,
            output_channels,
            ..
        } => {
            if ports["input"] != input_channels {
                return Err(invalid("declared input layout must match its source"));
            }
            output_channels
        }
        Definition::Reverb { .. } => {
            let input = ports["input"];
            if input.len() != 1 && !input.iter().map(Identifier::as_str).eq(["left", "right"]) {
                return Err(invalid(
                    "reverb requires mono or named left/right stereo input",
                ));
            }
            return names(["left", "right"]);
        }
        Definition::MatrixDelay {
            feedback_matrix, ..
        } => {
            if feedback_matrix.len() != ports["input"].len() {
                return Err(invalid(
                    "delay feedback matrix must match its input channel count",
                ));
            }
            ports["input"]
        }
        _ => ports["input"],
    };
    Ok(output.to_vec())
}

fn check_audio_processor(
    processors: &BTreeMap<Identifier, Processor>,
    name: &Identifier,
) -> Result<(), Error> {
    let processor = processors
        .get(name)
        .ok_or_else(|| invalid("unknown audio source processor"))?;
    if matches!(processor.0, Definition::Follower { .. }) {
        return Err(invalid("follower analysis cannot be an audio source"));
    }
    Ok(())
}

fn layered_order(
    dependencies: &BTreeMap<Identifier, BTreeSet<Identifier>>,
) -> Result<Vec<Identifier>, Error> {
    let mut remaining = BTreeMap::new();
    let mut dependents = BTreeMap::<_, Vec<_>>::new();
    for (node, prerequisites) in dependencies {
        remaining.insert(node, prerequisites.len());
        for prerequisite in prerequisites {
            dependents.entry(prerequisite).or_default().push(node);
        }
    }
    let mut ready: Vec<_> = remaining
        .iter()
        .filter_map(|(&node, &count)| (count == 0).then_some(node))
        .collect();
    let mut order = Vec::new();
    while !ready.is_empty() {
        ready.sort_unstable();
        let mut next = Vec::new();
        for node in ready {
            order.push(node.clone());
            if let Some(children) = dependents.get(node) {
                for &child in children {
                    let count = remaining.get_mut(child).expect("known dependent");
                    *count -= 1;
                    if *count == 0 {
                        next.push(child);
                    }
                }
            }
        }
        ready = next;
    }
    if order.len() != dependencies.len() {
        return Err(invalid("processor graph contains a cycle"));
    }
    Ok(order)
}

fn names<const N: usize>(values: [&str; N]) -> Result<Vec<Identifier>, Error> {
    values
        .into_iter()
        .map(|name| Identifier::new(name.to_owned()))
        .collect()
}

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
