//! Prepared MIDI 1 channel assignments and control mappings.

use crate::{envelfo::PreparationLimits, error::Error, identifier::Identifier};
use serde::Deserialize;
use std::collections::BTreeSet;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RepeatedKeyRelease {
    Oldest,
    Newest,
}

/// Bound destination for one decoded control value.
#[derive(Debug, PartialEq)]
pub struct ControlValue<'a> {
    pub part: &'a Identifier,
    pub control: &'a Identifier,
    pub value: f64,
}

/// Prepared MIDI channel layout and control mappings.
pub struct MidiBindings {
    inputs: Vec<Input>,
    channels: [Option<usize>; 16],
}

impl MidiBindings {
    pub(crate) fn decode(
        value: serde_json::Value,
        limits: PreparationLimits,
    ) -> Result<Self, Error> {
        let Definitions { midi: inputs } =
            serde_json::from_value(value).map_err(|error| invalid(error.to_string()))?;
        if inputs.is_empty() {
            return Err(invalid("MIDI bindings require at least one input"));
        }
        let mut records = 1;
        let mut channels = [None; 16];
        for (index, input) in inputs.iter().enumerate() {
            records += 1
                + input.channels.len()
                + input.controllers.len()
                + usize::from(input.pitch_bend.is_some());
            if records > limits.max_records() {
                return Err(Error::Limit("MIDI binding records"));
            }
            if input.channels.is_empty() {
                return Err(invalid("MIDI input requires at least one channel"));
            }
            for &channel in &input.channels {
                let slot = channel_index(channel)
                    .ok_or_else(|| invalid("MIDI channel must be in [1, 16]"))?;
                if channels[slot].replace(index).is_some() {
                    return Err(invalid("Duplicate MIDI channel"));
                }
            }
            let mut numbers = BTreeSet::new();
            for controller in &input.controllers {
                if controller.number > 127 || !numbers.insert(controller.number) {
                    return Err(invalid("Invalid or duplicate MIDI controller number"));
                }
                if !bipolar_range(controller.minimum, controller.maximum) {
                    return Err(invalid(
                        "MIDI controller output range must increase within [-1, 1]",
                    ));
                }
            }
            if let Some(bend) = &input.pitch_bend {
                if !(bipolar_range(bend.minimum, bend.maximum)
                    && bend.minimum < bend.center
                    && bend.center < bend.maximum)
                {
                    return Err(invalid(
                        "MIDI pitch-bend minimum < center < maximum required within [-1, 1]",
                    ));
                }
            }
        }
        Ok(Self { inputs, channels })
    }

    pub fn parts(&self) -> impl Iterator<Item = &Identifier> {
        let mut seen = BTreeSet::new();
        self.inputs
            .iter()
            .map(|input| &input.part)
            .filter(move |part| seen.insert(*part))
    }

    pub fn note_route(&self, channel: u8) -> Option<(&Identifier, RepeatedKeyRelease)> {
        let input = self.input(channel)?;
        Some((&input.part, input.repeated_key_release))
    }

    pub fn control_change(
        &self,
        channel: u8,
        controller: u8,
        value: u8,
    ) -> Result<Option<ControlValue<'_>>, Error> {
        if controller > 127 || value > 127 {
            return Err(invalid("MIDI controller and value must be in [0, 127]"));
        }
        Ok(self.input(channel).and_then(|input| {
            let mapping = input
                .controllers
                .iter()
                .find(|mapping| mapping.number == controller)?;
            let value = if value == 127 {
                mapping.maximum
            } else {
                mapping.minimum + (mapping.maximum - mapping.minimum) * f64::from(value) / 127.0
            };
            Some(ControlValue {
                part: &input.part,
                control: &mapping.control,
                value,
            })
        }))
    }

    pub fn pitch_bend(&self, channel: u8, value: i16) -> Result<Option<ControlValue<'_>>, Error> {
        if !(-8192..=8191).contains(&value) {
            return Err(invalid("MIDI pitch bend must be in [-8192, 8191]"));
        }
        Ok(self.input(channel).and_then(|input| {
            let bend = input.pitch_bend.as_ref()?;
            let value = match value {
                -8192 => bend.minimum,
                8191 => bend.maximum,
                v if v < 0 => bend.center + (bend.center - bend.minimum) * f64::from(v) / 8192.0,
                v => bend.center + (bend.maximum - bend.center) * f64::from(v) / 8191.0,
            };
            Some(ControlValue {
                part: &input.part,
                control: &bend.control,
                value,
            })
        }))
    }

    fn input(&self, channel: u8) -> Option<&Input> {
        let slot = channel_index(channel)?;
        self.channels[slot].map(|index| &self.inputs[index])
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Controller {
    number: u8,
    control: Identifier,
    #[serde(default)]
    minimum: f64,
    #[serde(default = "one")]
    maximum: f64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PitchBend {
    control: Identifier,
    #[serde(default = "negative_one")]
    minimum: f64,
    #[serde(default)]
    center: f64,
    #[serde(default = "one")]
    maximum: f64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    channels: Vec<u8>,
    part: Identifier,
    repeated_key_release: RepeatedKeyRelease,
    #[serde(default)]
    controllers: Vec<Controller>,
    #[serde(default)]
    pitch_bend: Option<PitchBend>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Definitions {
    midi: Vec<Input>,
}

fn channel_index(channel: u8) -> Option<usize> {
    channel
        .checked_sub(1)
        .filter(|index| *index < 16)
        .map(usize::from)
}

fn bipolar_range(minimum: f64, maximum: f64) -> bool {
    minimum >= -1.0 && maximum <= 1.0 && minimum < maximum
}

fn one() -> f64 {
    1.0
}
fn negative_one() -> f64 {
    -1.0
}

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
