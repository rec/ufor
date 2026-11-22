//! Ordered stored events and their public sequence outputs.

use crate::envelfo::PreparationLimits;
use crate::error::Error;
use crate::events::{EventKind, StoredEvent};
use crate::identifier::Identifier;
use crate::musical::header;
use crate::time::Timebase;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(try_from = "SequenceDefinition")]
pub struct EventSequence {
    timebase: Identifier,
    start: i64,
    end: i64,
    events: Vec<StoredEvent>,
}

impl EventSequence {
    pub fn new(
        timebase: Identifier,
        start: i64,
        end: i64,
        events: Vec<StoredEvent>,
    ) -> Result<Self, Error> {
        if end < start {
            return Err(invalid("sequence end precedes its start"));
        }
        let mut ordinals = BTreeSet::new();
        let mut last = None;
        for event in &events {
            if !ordinals.insert(event.ordinal) {
                return Err(invalid("duplicate event ordinal"));
            }
            let coordinate = (event.tick, event.ordinal);
            if last.is_some_and(|previous| coordinate < previous) {
                return Err(invalid("events must be in timestamp and ordinal order"));
            }
            if !(start..end).contains(&event.tick) {
                return Err(invalid("event is outside the sequence extent"));
            }
            last = Some(coordinate);
        }
        Ok(Self {
            timebase,
            start,
            end,
            events,
        })
    }

    pub fn timebase(&self) -> &Identifier {
        &self.timebase
    }

    pub fn start(&self) -> i64 {
        self.start
    }

    pub fn end(&self) -> i64 {
        self.end
    }

    pub fn events(&self) -> &[StoredEvent] {
        &self.events
    }

    pub(crate) fn check_toml(&self) -> Result<(), Error> {
        for event in &self.events {
            event.payload.check_toml()?;
        }
        Ok(())
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SequenceDefinition {
    timebase: Identifier,
    #[serde(default)]
    start: i64,
    end: i64,
    #[serde(default)]
    events: Vec<StoredEvent>,
}

impl TryFrom<SequenceDefinition> for EventSequence {
    type Error = Error;

    fn try_from(value: SequenceDefinition) -> Result<Self, Error> {
        Self::new(value.timebase, value.start, value.end, value.events)
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "ScoreDefinition", into = "ScoreDefinition")]
pub struct SequenceScore {
    name: String,
    title: String,
    tags: Vec<String>,
    timebases: Vec<Timebase>,
    outputs: Vec<SequenceOutput>,
    body: EventSequence,
}

impl SequenceScore {
    pub fn name(&self) -> &str {
        &self.name
    }

    pub fn title(&self) -> &str {
        &self.title
    }

    pub fn tags(&self) -> &[String] {
        &self.tags
    }

    pub fn timebases(&self) -> &[Timebase] {
        &self.timebases
    }

    pub fn outputs(&self) -> &[SequenceOutput] {
        &self.outputs
    }

    pub fn body(&self) -> &EventSequence {
        &self.body
    }

    pub(crate) fn check_records(&self, limits: PreparationLimits) -> Result<(), Error> {
        let count = 1 + self.timebases.len() + self.outputs.len() + self.body.events.len();
        if count > limits.max_records() {
            return Err(Error::Limit("sequence score records"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SequenceOutput {
    pub name: Identifier,
    pub stream: EventStream,
    binding: SequenceBinding,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EventStream {
    #[serde(default)]
    family: EventFamily,
    pub timebase: Identifier,
    pub kinds: Vec<EventKind>,
}

#[derive(Clone, Debug, Default, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum EventFamily {
    #[default]
    Event,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SequenceBinding {
    #[serde(default = "yes")]
    sequence: bool,
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
    timebases: Vec<Timebase>,
    #[serde(default)]
    inputs: Vec<serde_json::Value>,
    #[serde(default)]
    outputs: Vec<SequenceOutput>,
    #[serde(default)]
    parameters: Vec<serde_json::Value>,
    body: EventSequence,
}

impl TryFrom<ScoreDefinition> for SequenceScore {
    type Error = Error;

    fn try_from(value: ScoreDefinition) -> Result<Self, Error> {
        if value.format != "recs" || value.version != 4 || value.kind != "sequence" {
            return Err(invalid("expected a recs version 4 sequence score"));
        }
        if !value.inputs.is_empty() || !value.parameters.is_empty() {
            return Err(invalid("sequences have no inputs or parameters"));
        }
        let names: BTreeSet<_> = value.timebases.iter().map(Timebase::name).collect();
        if names.len() != value.timebases.len() {
            return Err(invalid("duplicate timebase name"));
        }
        if !names.contains(&value.body.timebase) {
            return Err(invalid("sequence references an unknown timebase"));
        }
        let mut outputs = BTreeSet::new();
        let event_kinds: BTreeSet<_> = value
            .body
            .events
            .iter()
            .map(|event| event.payload.kind())
            .collect();
        for output in &value.outputs {
            if !outputs.insert(&output.name) {
                return Err(invalid("duplicate output name"));
            }
            let kinds: BTreeSet<_> = output.stream.kinds.iter().copied().collect();
            if !output.binding.sequence
                || output.stream.timebase != value.body.timebase
                || kinds.is_empty()
                || kinds.len() != output.stream.kinds.len()
                || !kinds.is_superset(&event_kinds)
            {
                return Err(invalid("sequence export must match its native event body"));
            }
        }
        let tags = header(&value.name, &value.title, value.tags)?;
        Ok(Self {
            name: value.name,
            title: value.title,
            tags,
            timebases: value.timebases,
            outputs: value.outputs,
            body: value.body,
        })
    }
}

impl From<SequenceScore> for ScoreDefinition {
    fn from(value: SequenceScore) -> Self {
        Self {
            format: format(),
            version: version(),
            kind: kind(),
            name: value.name,
            title: value.title,
            tags: value.tags,
            timebases: value.timebases,
            inputs: Vec::new(),
            outputs: value.outputs,
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
    "sequence".into()
}

fn yes() -> bool {
    true
}

fn invalid(message: &str) -> Error {
    Error::Invalid(message.into())
}
