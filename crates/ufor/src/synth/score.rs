//! Versioned synth instrument scores and their public performance and audio ports.

use super::{InstrumentDefinition, SynthInstrument, invalid};
use crate::envelfo::PreparationLimits;
use crate::error::Error;
use crate::events::EventKind;
use crate::identifier::Identifier;
use crate::musical::header;
use crate::sequence::EventStream;
use crate::time::Timebase;
use serde::{Deserialize, Deserializer, Serialize};
use std::collections::BTreeSet;

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct SynthInstrumentScore {
    format: String,
    version: i64,
    kind: String,
    name: String,
    title: String,
    tags: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    description: Option<String>,
    timebases: Vec<Timebase>,
    inputs: [PerformanceInput; 1],
    outputs: [AudioOutput; 1],
    body: SynthInstrument,
}

impl SynthInstrumentScore {
    pub fn name(&self) -> &str {
        &self.name
    }

    pub fn title(&self) -> &str {
        &self.title
    }

    pub fn tags(&self) -> &[String] {
        &self.tags
    }

    pub fn description(&self) -> Option<&str> {
        self.description.as_deref()
    }

    pub fn timebases(&self) -> &[Timebase] {
        &self.timebases
    }

    pub fn input(&self) -> &PerformanceInput {
        &self.inputs[0]
    }

    pub fn output(&self) -> &AudioOutput {
        &self.outputs[0]
    }

    pub fn body(&self) -> &SynthInstrument {
        &self.body
    }

    pub fn into_body(self) -> SynthInstrument {
        self.body
    }
}

impl<'de> Deserialize<'de> for SynthInstrumentScore {
    fn deserialize<D: Deserializer<'de>>(decoder: D) -> Result<Self, D::Error> {
        ScoreWire::deserialize(decoder)?
            .prepare(PreparationLimits::default())
            .map_err(serde::de::Error::custom)
    }
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PerformanceInput {
    pub name: Identifier,
    pub stream: EventStream,
    binding: PerformanceBinding,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AudioOutput {
    pub name: Identifier,
    pub stream: AudioStream,
    binding: AudioBinding,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AudioStream {
    #[serde(default)]
    family: AudioFamily,
    #[serde(default)]
    quantity: AudioQuantity,
    #[serde(default)]
    unit: AudioUnit,
    pub timebase: Identifier,
    pub channels: Vec<String>,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum AudioFamily {
    #[default]
    Sampled,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum AudioQuantity {
    #[default]
    AudioAmplitude,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum AudioUnit {
    #[default]
    FullScale,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PerformanceBinding {
    #[serde(default = "yes")]
    performance: bool,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct AudioBinding {
    #[serde(default = "yes")]
    audio: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ScoreWire {
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
    description: Option<String>,
    timebases: Vec<Timebase>,
    inputs: [PerformanceInput; 1],
    outputs: [AudioOutput; 1],
    #[serde(default)]
    parameters: Vec<serde_json::Value>,
    body: InstrumentDefinition,
}

impl ScoreWire {
    pub(crate) fn prepare(self, limits: PreparationLimits) -> Result<SynthInstrumentScore, Error> {
        if self.format != "recs" || self.version != 4 || self.kind != "synth_instrument" {
            return Err(invalid("expected a recs version 4 synth instrument score"));
        }
        if !self.parameters.is_empty() {
            return Err(invalid("synth public parameter exports are unsupported"));
        }
        let tags = header(&self.name, &self.title, self.tags)?;
        let [input] = &self.inputs;
        let [output] = &self.outputs;
        let channels = validate_instrument_ports(&self.timebases, input, output)?;
        // The score and two port, stream and binding records share the body's budget.
        let remaining = limits
            .max_records()
            .checked_sub(7 + self.timebases.len())
            .filter(|&records| records > 0)
            .ok_or(Error::Limit("synth instrument score records"))?;
        let body = SynthInstrument::prepare(self.body, PreparationLimits::new(remaining)?)?;
        let routes = body
            .voices()
            .voices()
            .iter()
            .flat_map(|voice| voice.template().channels())
            .chain(
                body.tx81z_outputs()
                    .iter()
                    .flat_map(|output| output.channels()),
            );
        for route in routes {
            if route.input != "mono" || !channels.contains(route.output.as_str()) {
                return Err(invalid(
                    "Synth voice channel maps require mono input and known outputs",
                ));
            }
        }
        Ok(SynthInstrumentScore {
            format: self.format,
            version: self.version,
            kind: self.kind,
            name: self.name,
            title: self.title,
            tags,
            description: self.description,
            timebases: self.timebases,
            inputs: self.inputs,
            outputs: self.outputs,
            body,
        })
    }
}

pub(crate) fn validate_instrument_ports<'a>(
    timebases: &[Timebase],
    input: &PerformanceInput,
    output: &'a AudioOutput,
) -> Result<BTreeSet<&'a str>, Error> {
    let clocks: BTreeSet<_> = timebases.iter().map(Timebase::name).collect();
    if clocks.len() != timebases.len() {
        return Err(invalid("duplicate timebase name"));
    }
    if !clocks.contains(&input.stream.timebase) || !clocks.contains(&output.stream.timebase) {
        return Err(invalid(
            "public input/output references an unknown timebase",
        ));
    }
    let kinds: BTreeSet<_> = input.stream.kinds.iter().copied().collect();
    if !input.binding.performance
        || input.stream.kinds.len() != 3
        || kinds
            != BTreeSet::from([
                EventKind::Trigger,
                EventKind::Release,
                EventKind::ControlChange,
            ])
    {
        return Err(invalid(
            "instrument input must accept native performance events",
        ));
    }
    let channels: BTreeSet<_> = output.stream.channels.iter().map(String::as_str).collect();
    if !output.binding.audio
        || output.stream.channels.is_empty()
        || channels.contains("")
        || channels.len() != output.stream.channels.len()
    {
        return Err(invalid(
            "audio output requires distinct nonempty channel names",
        ));
    }
    Ok(channels)
}

fn format() -> String {
    "recs".into()
}

fn version() -> i64 {
    4
}

fn kind() -> String {
    "synth_instrument".into()
}

fn yes() -> bool {
    true
}
