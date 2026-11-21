//! Authored effect actions and graph-dependent validation.
use super::{Definition, Domain, Processor, topology::Topology};
use crate::{error::Error, identifier::Identifier, quantity};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(try_from = "Record")]
pub struct Action(Record);

impl Action {
    pub fn tick(&self) -> i64 {
        self.order().0
    }

    pub fn ordinal(&self) -> i64 {
        self.order().1
    }

    pub fn lifecycle(&self) -> bool {
        matches!(
            self.0,
            Record::InputEnd { .. } | Record::Stop { .. } | Record::CaptureRelease { .. }
        )
    }

    fn order(&self) -> (i64, i64) {
        match &self.0 {
            Record::Parameter { tick, ordinal, .. }
            | Record::Bypass { tick, ordinal, .. }
            | Record::Freeze { tick, ordinal, .. }
            | Record::Capture { tick, ordinal, .. }
            | Record::CaptureRelease { tick, ordinal, .. }
            | Record::InputEnd { tick, ordinal, .. }
            | Record::Stop { tick, ordinal, .. } => (*tick, *ordinal),
        }
    }
}

impl TryFrom<Record> for Action {
    type Error = Error;

    fn try_from(mut record: Record) -> Result<Self, Error> {
        if let Record::Parameter {
            parameter,
            value,
            duration_frames,
            ..
        } = &mut record
        {
            if *duration_frames < 0 {
                return Err(invalid("effect action duration must be nonnegative"));
            }
            *value = Scalar::Number(match value {
                Scalar::Number(value) => quantity::finite(*value)?,
                Scalar::Text(text) => action_scalar(parameter.as_str(), text)?,
            });
        }
        let action = Self(record);
        if action.tick() < 0 || action.ordinal() < 0 {
            return Err(invalid(
                "effect action tick and ordinal must be nonnegative",
            ));
        }
        Ok(action)
    }
}

/// A nonempty ordered set of actions at one frame.
#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(try_from = "BatchBody")]
pub struct ActionBatch {
    actions: Vec<Action>,
}

impl ActionBatch {
    pub fn actions(&self) -> &[Action] {
        &self.actions
    }

    pub fn lifecycle(&self) -> bool {
        self.actions.iter().any(Action::lifecycle)
    }
}

impl TryFrom<BatchBody> for ActionBatch {
    type Error = Error;

    fn try_from(body: BatchBody) -> Result<Self, Error> {
        let actions = body.actions;
        let first = actions
            .first()
            .ok_or_else(|| invalid("an action batch requires at least one action"))?;
        if actions.iter().any(|action| action.tick() != first.tick()) {
            return Err(invalid("an action batch represents one frame event"));
        }
        if actions
            .windows(2)
            .any(|pair| pair[0].ordinal() >= pair[1].ordinal())
        {
            return Err(invalid("batch action ordinals must strictly increase"));
        }
        Ok(Self { actions })
    }
}

impl Topology {
    pub fn validate_action(&self, action: &Action) -> Result<(), Error> {
        let processor = match &action.0 {
            Record::Parameter { processor, .. }
            | Record::Bypass { processor, .. }
            | Record::Freeze { processor, .. }
            | Record::Capture { processor, .. }
            | Record::CaptureRelease { processor, .. } => self
                .processors
                .get(processor)
                .ok_or_else(|| invalid(format!("unknown processor {}", processor.as_str())))?,
            Record::InputEnd { input, .. } => {
                return if self.inputs.contains(input) {
                    Ok(())
                } else {
                    Err(invalid(format!("unknown graph input {}", input.as_str())))
                };
            }
            Record::Stop { .. } => return Ok(()),
        };
        match (&action.0, &processor.0) {
            (
                Record::Capture { .. } | Record::CaptureRelease { .. },
                Definition::CapturedBuffer { .. },
            ) => Ok(()),
            (Record::Capture { .. } | Record::CaptureRelease { .. }, _) => {
                Err(invalid("capture actions require a captured buffer"))
            }
            (_, Definition::Matrix { .. }) => Err(invalid(
                "routing matrices have no parameter, bypass or freeze actions",
            )),
            (_, Definition::Convolution { .. }) => Err(invalid(
                "convolution is always wet; control mix through routing nodes",
            )),
            (
                Record::Parameter {
                    parameter,
                    value: Scalar::Number(value),
                    duration_frames,
                    ..
                },
                _,
            ) => validate_parameter(processor, parameter.as_str(), *value, *duration_frames),
            (_, Definition::MultibandCompressor { .. }) => Err(invalid(
                "multiband compression is always wet; use routing nodes",
            )),
            (
                Record::Bypass { .. },
                Definition::Mixer { .. }
                | Definition::Crossfader { .. }
                | Definition::Follower { .. },
            ) => Err(invalid("mixers, crossfaders and followers have no bypass")),
            (Record::Freeze { .. }, Definition::Granulator { .. }) | (Record::Bypass { .. }, _) => {
                Ok(())
            }
            (Record::Freeze { .. }, _) => Err(invalid("freeze actions require a granulator")),
            _ => unreachable!("checked action"),
        }
    }

    pub fn validate_batch(&self, batch: &ActionBatch, maximum_actions: usize) -> Result<(), Error> {
        if batch.actions.len() > maximum_actions {
            return Err(invalid("action batch exceeds graph capacity"));
        }
        for action in &batch.actions {
            self.validate_action(action)?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Record {
    Parameter {
        tick: i64,
        ordinal: i64,
        processor: Identifier,
        parameter: Identifier,
        value: Scalar,
        #[serde(default)]
        duration_frames: i64,
    },
    Bypass {
        tick: i64,
        ordinal: i64,
        processor: Identifier,
        bypassed: bool,
    },
    Freeze {
        tick: i64,
        ordinal: i64,
        processor: Identifier,
        frozen: bool,
    },
    Capture {
        tick: i64,
        ordinal: i64,
        processor: Identifier,
    },
    CaptureRelease {
        tick: i64,
        ordinal: i64,
        processor: Identifier,
    },
    InputEnd {
        tick: i64,
        ordinal: i64,
        input: Identifier,
    },
    Stop {
        tick: i64,
        ordinal: i64,
    },
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(untagged)]
enum Scalar {
    Number(f64),
    Text(String),
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BatchBody {
    actions: Vec<Action>,
}

fn validate_parameter(
    processor: &Processor,
    field: &str,
    value: f64,
    duration: i64,
) -> Result<(), Error> {
    let selector = match (&processor.0, field.rsplit_once('-')) {
        (Definition::Mixer { inputs, .. }, Some((port, "muted" | "solo"))) => {
            inputs.iter().any(|input| input.name.as_str() == port)
        }
        _ => false,
    };
    if selector {
        if !matches!(value, 0.0 | 1.0) {
            return Err(invalid("mixer selectors must be zero or one"));
        }
        if duration != 0 {
            return Err(invalid(
                "mixer selectors are immediate requests with internal fades",
            ));
        }
        return Ok(());
    }
    let facts = processor.resolve_target(field).ok_or_else(|| {
        invalid(format!(
            "unsupported parameter {}.{field}",
            processor.name().as_str()
        ))
    })?;
    facts.domain.check(value)?;
    if matches!(facts.domain, Domain::Integer(..)) && duration != 0 {
        return Err(invalid("bitcrusher integer controls do not accept ramps"));
    }
    Ok(())
}

fn action_scalar(parameter: &str, text: &str) -> Result<f64, Error> {
    let field = parameter.rsplit('-').next().unwrap_or(parameter);
    let unit = match field {
        "gain_db" | "threshold_db" | "maximum_cut_db" | "hysteresis_db" | "knee_db"
        | "makeup_db" | "output_gain_db" | "ceiling_db" | "attack_gain_db" | "sustain_gain_db" => {
            "db"
        }
        "attack_seconds" | "release_seconds" | "hold_seconds" | "predelay_seconds"
        | "decay_seconds" | "delay_seconds" | "base_delay_seconds" | "depth_seconds"
        | "duration_seconds" => "seconds",
        "damping_hz" | "center_hz" | "shift_hz" | "cutoff_hz" | "rate_hz" | "density_hz" => "hz",
        "depth_cents" => "cents",
        "ratio" | "mix" | "position" | "drive" | "bits" | "feedback" | "playback_ratio" => "ratio",
        "hold_frames" => {
            let text = text.trim();
            let text = text
                .strip_suffix("frames")
                .or_else(|| text.strip_suffix("frame"))
                .unwrap_or(text);
            return quantity::scalar(text, "ratio");
        }
        _ => {
            return Err(invalid(
                "effect action value requires numeric input for this parameter",
            ));
        }
    };
    quantity::scalar(text, unit)
}

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
