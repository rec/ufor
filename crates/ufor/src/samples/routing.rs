//! Portable channel routes and static sampler pan laws.

use crate::{error::Error, quantity};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::f64::consts::{FRAC_1_SQRT_2, PI, SQRT_2};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PanLaw {
    #[default]
    Native,
    Sfizz,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ChannelRoute {
    pub input: String,
    pub output: String,
    pub gain: f64,
}

/// Absolute stereo gains for a mono pan or stereo balance position.
pub fn pan_gains(position: f64, law: PanLaw, stereo: bool) -> Result<[f64; 2], Error> {
    if !(-1.0..=1.0).contains(&position) {
        return Err(invalid("pan position must be between -1 and 1"));
    }
    if stereo && law == PanLaw::Native {
        return Ok([1.0 - position.max(0.0), 1.0 + position.min(0.0)]);
    }
    let angle = (position + 1.0) * PI / 4.0;
    let left = if position == 1.0 { 0.0 } else { angle.cos() };
    let right = if position == -1.0 { 0.0 } else { angle.sin() };
    let compensation = match (law, stereo) {
        (PanLaw::Native, _) => 1.0,
        (PanLaw::Sfizz, true) => 10_f64.powf(6.0 / 20.0) / SQRT_2,
        (PanLaw::Sfizz, false) => 10_f64.powf(3.0 / 20.0),
    };
    Ok([left * compensation, right * compensation])
}

/// Resolve named routes into rows in input order and columns in output order.
pub fn channel_matrix(
    inputs: &[String],
    outputs: &[String],
    routes: &[ChannelRoute],
) -> Result<Vec<Vec<f64>>, Error> {
    check_layout(inputs)?;
    check_layout(outputs)?;
    let mut matrix = vec![vec![0.0; outputs.len()]; inputs.len()];
    let mut occupied = BTreeSet::new();
    for route in routes {
        let input = inputs
            .iter()
            .position(|name| name == &route.input)
            .ok_or_else(|| invalid("unknown route input channel"))?;
        let output = outputs
            .iter()
            .position(|name| name == &route.output)
            .ok_or_else(|| invalid("unknown route output channel"))?;
        if !occupied.insert((input, output)) {
            return Err(invalid("duplicate channel route"));
        }
        matrix[input][output] = quantity::finite(route.gain)?;
    }
    Ok(matrix)
}

/// Apply sampler pan to an explicit matrix for a supported stereo layout.
pub fn sampler_matrix(
    inputs: &[String],
    outputs: &[String],
    routes: &[ChannelRoute],
    law: PanLaw,
    pan: f64,
    balance: f64,
) -> Result<Vec<Vec<f64>>, Error> {
    let mut matrix = channel_matrix(inputs, outputs, routes)?;
    if outputs == ["left", "right"] {
        let gains = if inputs == ["mono"] {
            Some(pan_gains(pan, law, false)?.map(|gain| gain / FRAC_1_SQRT_2))
        } else if inputs == ["left", "right"] {
            Some(pan_gains(balance, law, true)?)
        } else {
            None
        };
        if let Some(gains) = gains {
            for row in &mut matrix {
                for (value, gain) in row.iter_mut().zip(gains) {
                    *value = quantity::finite(*value * gain)?;
                }
            }
        }
    }
    Ok(matrix)
}

fn check_layout(channels: &[String]) -> Result<(), Error> {
    let mut seen = BTreeSet::new();
    if channels.is_empty()
        || channels
            .iter()
            .any(|name| name.is_empty() || !seen.insert(name))
    {
        return Err(invalid(
            "channel layouts must contain distinct nonempty names",
        ));
    }
    Ok(())
}

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
