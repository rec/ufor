//! Generator-aware validation of supplied facts, with explicit external work.
use super::controls::ControlDeclaration;
use super::processing::{
    self, Binding, EnvelfoEventConnection, FollowerBinding, GeneratorBinding, ReleaseTiming,
};
use crate::control::{Polarity, Scope};
use crate::envelfo::{self, Body, Clock, Generator, PatchNode, PreparationLimits, Rate, Reset};
use crate::error::Error;
use crate::identifier::Identifier;
use crate::modulation::{Modulation, Source, SourceScope, Target};
use serde::Serialize;
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum GeneratorRequirement {
    Output,
    Domain,
    Release,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ConnectionRequirement {
    SourcePort,
    DestinationCue,
}
#[derive(Clone, Copy, Debug, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum PendingKind {
    Generator,
}
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct UnresolvedGeneratorBinding {
    kind: PendingKind,
    binding: GeneratorBinding,
    checks: Vec<GeneratorRequirement>,
}
impl UnresolvedGeneratorBinding {
    pub fn binding(&self) -> &GeneratorBinding {
        &self.binding
    }
    pub fn checks(&self) -> &[GeneratorRequirement] {
        &self.checks
    }
}
#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(untagged)]
pub enum OutstandingBinding {
    Generator(UnresolvedGeneratorBinding),
    Follower(FollowerBinding),
}
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct UnresolvedEventConnection {
    connection: EnvelfoEventConnection,
    checks: Vec<ConnectionRequirement>,
}
impl UnresolvedEventConnection {
    pub fn connection(&self) -> &EnvelfoEventConnection {
        &self.connection
    }
    pub fn checks(&self) -> &[ConnectionRequirement] {
        &self.checks
    }
}
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct BindingValidation {
    unresolved_bindings: Vec<OutstandingBinding>,
    unresolved_connections: Vec<UnresolvedEventConnection>,
    unresolved_targets: Vec<Target>,
}
impl BindingValidation {
    pub fn unresolved_bindings(&self) -> &[OutstandingBinding] {
        &self.unresolved_bindings
    }
    pub fn unresolved_connections(&self) -> &[UnresolvedEventConnection] {
        &self.unresolved_connections
    }
    pub fn unresolved_targets(&self) -> &[Target] {
        &self.unresolved_targets
    }
}

pub fn validate_generator_bindings(
    definition: &Modulation,
    bindings: &[Binding],
    controls: &BTreeMap<Identifier, ControlDeclaration>,
    generators: &BTreeMap<Identifier, Generator>,
    connections: &[EnvelfoEventConnection],
    limits: PreparationLimits,
) -> Result<BindingValidation, Error> {
    envelfo::preparation_records(
        &serde_json::json!({"modulation":definition,"bindings":bindings,"controls":controls,"envelfos":generators,"event_connections":connections}),
        limits,
    )?;
    processing::validate_local_with_limit(definition, bindings, controls, limits.max_records())?;
    for g in generators.values() {
        match g.body() {
            Body::Lfo(v) if matches!(v.rate(), Rate::Parameter(_)) => {
                return Err(invalid("inline LFO requires literal rate"));
            }
            Body::Envelope(v) if matches!(v.initial(), envelfo::Initial::Current) => {
                return Err(invalid("current envelope initial requires a parent stage"));
            }
            _ => (),
        }
    }
    let sources: BTreeMap<_, _> = definition.sources().iter().map(|s| (s.name(), s)).collect();
    let by_name: BTreeMap<_, _> = bindings.iter().map(|b| (b.name(), b)).collect();
    let mut pending = Vec::new();
    let mut timings = BTreeMap::new();
    for binding in bindings {
        match binding {
            Binding::Follower(v) => pending.push(OutstandingBinding::Follower(v.clone())),
            Binding::Generator(v) => {
                let generator = generators
                    .get(v.reference())
                    .ok_or_else(|| invalid("unknown local generator"))?;
                let source = sources[v.name()];
                if matches!(generator.body(), Body::Reference(_)) {
                    if !scope(source.scope(), generator.settings().scope()) {
                        return Err(invalid("reference scope mismatch"));
                    }
                    let mut checks =
                        vec![GeneratorRequirement::Output, GeneratorRequirement::Domain];
                    if v.release_timing() == ReleaseTiming::Voice {
                        checks.push(GeneratorRequirement::Release);
                    }
                    pending.push(OutstandingBinding::Generator(UnresolvedGeneratorBinding {
                        kind: PendingKind::Generator,
                        binding: v.clone(),
                        checks,
                    }));
                } else {
                    generator_source(source, v, generator, &mut timings)?;
                }
            }
            _ => (),
        }
    }
    let mut events = Vec::new();
    for connection in connections {
        let checks = event(connection, &by_name, generators)?;
        if !checks.is_empty() {
            events.push(UnresolvedEventConnection {
                connection: connection.clone(),
                checks,
            });
        }
    }
    Ok(BindingValidation {
        unresolved_bindings: pending,
        unresolved_connections: events,
        unresolved_targets: definition
            .parameters()
            .iter()
            .map(|p| p.target().clone())
            .collect(),
    })
}
fn scope(source: SourceScope, target: Scope) -> bool {
    matches!(
        (source, target),
        (SourceScope::Voice, Scope::Voice)
            | (SourceScope::Instrument, Scope::Instrument)
            | (SourceScope::Part, Scope::Part)
    )
}
fn generator_source(
    source: &Source,
    binding: &GeneratorBinding,
    g: &Generator,
    timings: &mut BTreeMap<(Identifier, Identifier), ReleaseTiming>,
) -> Result<(), Error> {
    let mut selected = g;
    let mut derived = None;
    if let Body::Patch(patch) = g.body() {
        let output = binding
            .output()
            .ok_or_else(|| invalid("Patch binding requires named output"))?;
        let child = &patch
            .outputs()
            .iter()
            .find(|(n, _)| n == output)
            .ok_or_else(|| invalid("unknown Patch output"))?
            .1;
        let key = (binding.reference().clone(), child.clone());
        if timings
            .get(&key)
            .is_some_and(|t| *t != binding.release_timing())
        {
            return Err(invalid("conflicting Patch child release timing"));
        }
        timings.insert(key, binding.release_timing());
        let node = &patch
            .envelfos()
            .iter()
            .find(|(n, _)| n == child)
            .ok_or_else(|| invalid("unknown Patch child"))?
            .1;
        match node {
            PatchNode::Generator(v) => selected = v,
            PatchNode::Signal(_) => {
                derived = Some(
                    patch
                        .signal_ranges()
                        .iter()
                        .find(|(n, _)| n == child)
                        .ok_or_else(|| invalid("missing signal range"))?
                        .1,
                )
            }
        }
    } else if binding.output().is_some() {
        return Err(invalid("only Patch selects outputs"));
    }
    if binding.release_timing() == ReleaseTiming::Voice
        && (derived.is_some()
            || !matches!(selected.body(),Body::Envelope(v) if !v.release().is_empty()))
    {
        return Err(invalid("voice timing requires a releasing envelope"));
    }
    if !scope(source.scope(), g.settings().scope()) {
        return Err(invalid("generator source scope mismatch"));
    }
    if let Some((low, high)) = derived {
        if source.minimum() > low || source.maximum() < high {
            return Err(invalid("Patch output exceeds source domain"));
        }
    } else {
        let low = if matches!(selected.body(),Body::Envelope(v) if v.polarity()==Polarity::Unipolar)
        {
            0.0
        } else {
            -1.0
        };
        if source.minimum() != low || source.maximum() != 1.0 {
            return Err(invalid("generator source domain mismatch"));
        }
    }
    Ok(())
}
fn event(
    c: &EnvelfoEventConnection,
    bindings: &BTreeMap<&Identifier, &Binding>,
    generators: &BTreeMap<Identifier, Generator>,
) -> Result<Vec<ConnectionRequirement>, Error> {
    let source = match bindings.get(c.source()) {
        Some(Binding::Generator(v)) => v,
        _ => return Err(invalid("event source must bind a generator")),
    };
    let destination = match bindings.get(c.destination()) {
        Some(Binding::Generator(v)) => v,
        _ => return Err(invalid("event destination must bind a generator")),
    };
    let origin = generators
        .get(source.reference())
        .ok_or_else(|| invalid("unknown event generator"))?;
    let target = generators
        .get(destination.reference())
        .ok_or_else(|| invalid("unknown event generator"))?;
    if origin.settings().scope() != Scope::Voice || target.settings().scope() != Scope::Voice {
        return Err(invalid("generator events require voice scope"));
    }
    let mut checks = Vec::new();
    let present = match origin.body() {
        Body::Reference(_) => {
            checks.push(ConnectionRequirement::SourcePort);
            true
        }
        Body::Patch(p) => p
            .event_outputs()
            .iter()
            .any(|(n, _)| n.as_str() == c.port()),
        Body::Stages(s) => s.event_ports().iter().any(|p| p == c.port()),
        Body::Lfo(l) => {
            if origin.settings().clock() != Clock::Seconds
                || !matches!(l.rate(),Rate::Literal(v) if v.numerator()!=0)
                || l.reset() != Reset::Trigger
                || l.delay().numerator() != 0
                || l.fade_in().numerator() != 0
            {
                return Err(invalid("event LFO requires simple seconds profile"));
            }
            l.markers().iter().any(|m| m.name().as_str() == c.port())
        }
        _ => false,
    };
    if !present {
        return Err(invalid("unknown generator event port"));
    }
    match target.body() {
        Body::Reference(_) => checks.push(ConnectionRequirement::DestinationCue),
        Body::Stages(s)
            if s.transitions()
                .iter()
                .any(|t| t.event() == format!("cue.{}", c.cue().as_str())) => {}
        _ => return Err(invalid("event destination has no matching cue")),
    }
    Ok(checks)
}
fn invalid(message: &str) -> Error {
    Error::Invalid(message.into())
}
