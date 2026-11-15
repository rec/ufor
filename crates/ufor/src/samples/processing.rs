//! Binding declarations and local checks; generator/processor resolution is external.
use super::controls::ControlDeclaration;
use crate::control::Polarity;
use crate::error::Error;
use crate::identifier::Identifier;
use crate::modulation::{Modulation, SourceScope};
use crate::number::Rational;
use crate::quantity::{exact_seconds, records};
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum EventKind {
    Key,
    Velocity,
}
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ReleaseTiming {
    #[default]
    Event,
    Voice,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "EventDefinition", into = "EventDefinition")]
pub struct EventBinding {
    name: Identifier,
    kind: EventKind,
}
impl EventBinding {
    pub fn new(name: Identifier, kind: EventKind) -> Self {
        Self { name, kind }
    }
    pub fn name(&self) -> &Identifier {
        &self.name
    }
    pub fn kind(&self) -> EventKind {
        self.kind
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "ControlDefinition", into = "ControlDefinition")]
pub struct ControlBinding {
    name: Identifier,
    control: Identifier,
    smoothing: Rational,
}
impl ControlBinding {
    pub fn new(name: Identifier, control: Identifier, smoothing: Rational) -> Result<Self, Error> {
        if smoothing.numerator() < 0 {
            return Err(invalid("negative smoothing"));
        }
        Ok(Self {
            name,
            control,
            smoothing,
        })
    }
    pub fn name(&self) -> &Identifier {
        &self.name
    }
    pub fn control(&self) -> &Identifier {
        &self.control
    }
    pub fn smoothing(&self) -> Rational {
        self.smoothing
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "GeneratorDefinition", into = "GeneratorDefinition")]
pub struct GeneratorBinding {
    name: Identifier,
    reference: Identifier,
    output: Option<Identifier>,
    release_timing: ReleaseTiming,
}
impl GeneratorBinding {
    pub fn new(
        name: Identifier,
        reference: Identifier,
        output: Option<Identifier>,
        release_timing: ReleaseTiming,
    ) -> Self {
        Self {
            name,
            reference,
            output,
            release_timing,
        }
    }
    pub fn name(&self) -> &Identifier {
        &self.name
    }
    pub fn reference(&self) -> &Identifier {
        &self.reference
    }
    pub fn output(&self) -> Option<&Identifier> {
        self.output.as_ref()
    }
    pub fn release_timing(&self) -> ReleaseTiming {
        self.release_timing
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "FollowerDefinition", into = "FollowerDefinition")]
pub struct FollowerBinding {
    name: Identifier,
    processor: Identifier,
}
impl FollowerBinding {
    pub fn new(name: Identifier, processor: Identifier) -> Self {
        Self { name, processor }
    }
    pub fn name(&self) -> &Identifier {
        &self.name
    }
    pub fn processor(&self) -> &Identifier {
        &self.processor
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum Binding {
    Event(EventBinding),
    Control(ControlBinding),
    Generator(GeneratorBinding),
    Follower(FollowerBinding),
}
impl Binding {
    pub fn name(&self) -> &Identifier {
        match self {
            Self::Event(v) => &v.name,
            Self::Control(v) => &v.name,
            Self::Generator(v) => &v.name,
            Self::Follower(v) => &v.name,
        }
    }
}
impl Serialize for Binding {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match self {
            Self::Event(v) => v.serialize(serializer),
            Self::Control(v) => v.serialize(serializer),
            Self::Generator(v) => v.serialize(serializer),
            Self::Follower(v) => v.serialize(serializer),
        }
    }
}
impl<'de> Deserialize<'de> for Binding {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let result = match BindingDefinition::deserialize(deserializer)? {
            BindingDefinition::Key(mut v) => {
                v.kind = Some(EventKind::Key);
                EventBinding::try_from(v).map(Self::Event)
            }
            BindingDefinition::Velocity(mut v) => {
                v.kind = Some(EventKind::Velocity);
                EventBinding::try_from(v).map(Self::Event)
            }
            BindingDefinition::Control(v) => ControlBinding::try_from(v).map(Self::Control),
            BindingDefinition::Envelfo(v) => GeneratorBinding::try_from(v).map(Self::Generator),
            BindingDefinition::Follower(v) => FollowerBinding::try_from(v).map(Self::Follower),
        };
        result.map_err(serde::de::Error::custom)
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(untagged)]
pub enum UnresolvedBinding {
    Generator(GeneratorBinding),
    Follower(FollowerBinding),
}

/// Returns unresolved generator/follower declarations in binding order.
/// Success establishes only local facts, never full ModulationSettings validity.
#[must_use = "generator and follower references still require external resolution"]
pub fn validate_local_bindings(
    definition: &Modulation,
    bindings: &[Binding],
    controls: &BTreeMap<Identifier, ControlDeclaration>,
) -> Result<Vec<UnresolvedBinding>, Error> {
    records(bindings.len())?;
    records(controls.len())?;
    records(definition.record_count() + bindings.len() + controls.len())?;
    let sources: BTreeMap<_, _> = definition.sources().iter().map(|s| (s.name(), s)).collect();
    let names: BTreeSet<_> = bindings.iter().map(Binding::name).collect();
    if names.len() != bindings.len()
        || names.len() != sources.len()
        || names.iter().any(|n| !sources.contains_key(n))
    {
        return Err(invalid("each source requires exactly one binding"));
    }
    let mut unresolved = Vec::new();
    for binding in bindings {
        let source = sources
            .get(binding.name())
            .ok_or_else(|| invalid("unknown binding source"))?;
        match binding {
            Binding::Control(binding) => {
                let declaration = controls
                    .get(&binding.control)
                    .ok_or_else(|| invalid("unknown control declaration"))?;
                let minimum = if declaration.polarity() == Polarity::Bipolar {
                    -1.0
                } else {
                    0.0
                };
                if source.scope() == SourceScope::Voice
                    || source.minimum() != minimum
                    || source.maximum() != 1.0
                {
                    return Err(invalid("control source must match declaration and scope"));
                }
            }
            Binding::Event(binding) => {
                if source.scope() != SourceScope::Voice {
                    return Err(invalid("key/velocity source must be voice scoped"));
                }
                match binding.kind {
                    EventKind::Velocity if source.minimum() != 0.0 || source.maximum() != 1.0 => {
                        return Err(invalid("velocity source domain must be [0,1]"));
                    }
                    EventKind::Key
                        if source.minimum().fract() != 0.0
                            || source.maximum().fract() != 0.0
                            || definition
                                .routes()
                                .iter()
                                .filter(|r| r.source() == source.name())
                                .any(|r| r.points().iter().any(|p| p.input().fract() != 0.0)) =>
                    {
                        return Err(invalid("key bounds and mapping inputs must be integers"));
                    }
                    _ => (),
                }
            }
            Binding::Generator(binding) => {
                unresolved.push(UnresolvedBinding::Generator(binding.clone()))
            }
            Binding::Follower(binding) => {
                if source.scope() != SourceScope::Voice || source.minimum() != 0.0 {
                    return Err(invalid(
                        "follower source must be voice scoped with minimum zero",
                    ));
                }
                unresolved.push(UnresolvedBinding::Follower(binding.clone()));
            }
        }
    }
    Ok(unresolved)
}

fn invalid(message: &str) -> Error {
    Error::Invalid(message.into())
}
fn control_kind() -> String {
    "control".into()
}
fn generator_kind() -> String {
    "envelfo".into()
}
fn follower_kind() -> String {
    "follower".into()
}
fn smoothing() -> Smoothing {
    Smoothing::Text("1/200".into())
}
#[derive(Serialize, Deserialize)]
#[serde(untagged)]
enum Smoothing {
    Integer(i64),
    Text(String),
}
impl Smoothing {
    fn value(self) -> Result<Rational, Error> {
        match self {
            Self::Integer(v) => exact_seconds(&v.to_string()),
            Self::Text(v) => exact_seconds(&v),
        }
    }
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct EventDefinition {
    name: Identifier,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    kind: Option<EventKind>,
}
impl TryFrom<EventDefinition> for EventBinding {
    type Error = Error;
    fn try_from(v: EventDefinition) -> Result<Self, Error> {
        Ok(Self::new(
            v.name,
            v.kind
                .ok_or_else(|| invalid("event binding requires kind"))?,
        ))
    }
}
impl From<EventBinding> for EventDefinition {
    fn from(v: EventBinding) -> Self {
        Self {
            name: v.name,
            kind: Some(v.kind),
        }
    }
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ControlDefinition {
    name: Identifier,
    #[serde(default = "control_kind")]
    kind: String,
    control: Identifier,
    #[serde(default = "smoothing")]
    smoothing: Smoothing,
}
impl TryFrom<ControlDefinition> for ControlBinding {
    type Error = Error;
    fn try_from(v: ControlDefinition) -> Result<Self, Error> {
        if v.kind != "control" {
            return Err(invalid("expected control binding"));
        }
        Self::new(v.name, v.control, v.smoothing.value()?)
    }
}
impl From<ControlBinding> for ControlDefinition {
    fn from(v: ControlBinding) -> Self {
        Self {
            name: v.name,
            kind: control_kind(),
            control: v.control,
            smoothing: Smoothing::Text(v.smoothing.to_string()),
        }
    }
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct GeneratorDefinition {
    name: Identifier,
    #[serde(default = "generator_kind")]
    kind: String,
    reference: Identifier,
    #[serde(default)]
    output: Option<Identifier>,
    #[serde(default)]
    release_timing: ReleaseTiming,
}
impl TryFrom<GeneratorDefinition> for GeneratorBinding {
    type Error = Error;
    fn try_from(v: GeneratorDefinition) -> Result<Self, Error> {
        if v.kind != "envelfo" {
            return Err(invalid("expected envelfo binding"));
        }
        Ok(Self::new(v.name, v.reference, v.output, v.release_timing))
    }
}
impl From<GeneratorBinding> for GeneratorDefinition {
    fn from(v: GeneratorBinding) -> Self {
        Self {
            name: v.name,
            kind: generator_kind(),
            reference: v.reference,
            output: v.output,
            release_timing: v.release_timing,
        }
    }
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct FollowerDefinition {
    name: Identifier,
    #[serde(default = "follower_kind")]
    kind: String,
    processor: Identifier,
}
impl TryFrom<FollowerDefinition> for FollowerBinding {
    type Error = Error;
    fn try_from(v: FollowerDefinition) -> Result<Self, Error> {
        if v.kind != "follower" {
            return Err(invalid("expected follower binding"));
        }
        Ok(Self::new(v.name, v.processor))
    }
}
impl From<FollowerBinding> for FollowerDefinition {
    fn from(v: FollowerBinding) -> Self {
        Self {
            name: v.name,
            kind: follower_kind(),
            processor: v.processor,
        }
    }
}
#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
enum BindingDefinition {
    Key(EventDefinition),
    Velocity(EventDefinition),
    Control(ControlDefinition),
    Envelfo(GeneratorDefinition),
    Follower(FollowerDefinition),
}
