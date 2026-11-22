//! Portable channel routes and static sampler pan laws.

use super::processing::{Binding, SoundSettings};
use crate::{envelfo::Body, error::Error, modulation::Operation, quantity};
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

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SpatialTarget {
    Pan,
    StereoBalance,
}

impl SpatialTarget {
    fn parameter(self) -> &'static str {
        match self {
            Self::Pan => "pan",
            Self::StereoBalance => "stereo_balance",
        }
    }
}

/// Conservative range of a pan or balance parameter in one settings layer.
///
/// Materialize generator references before using these bounds for playback.
/// A delayed or fading inline LFO includes the neutral value of each route.
pub fn spatial_bounds(
    settings: &SoundSettings,
    target: SpatialTarget,
) -> Result<(f64, f64), Error> {
    let base = match target {
        SpatialTarget::Pan => settings.processing().pan(),
        SpatialTarget::StereoBalance => settings.processing().stereo_balance(),
    };
    let fading: BTreeSet<_> = settings
        .envelfos()
        .iter()
        .filter_map(|(name, generator)| match generator.body() {
            Body::Lfo(lfo) if lfo.delay().numerator() != 0 || lfo.fade_in().numerator() != 0 => {
                Some(name)
            }
            _ => None,
        })
        .collect();
    let weighted: BTreeSet<_> = settings
        .bindings()
        .iter()
        .filter_map(|binding| match binding {
            Binding::Generator(binding) if fading.contains(binding.reference()) => {
                Some(binding.name())
            }
            _ => None,
        })
        .collect();
    let mut low = base;
    let mut high = base;
    let mut multipliers = Vec::new();
    for route in settings.modulation().routes().iter().filter(|route| {
        route.target().name().as_str() == "processing"
            && route.target().parameter().as_str() == target.parameter()
    }) {
        let neutral = match route.operation() {
            Operation::Add => 0.0,
            Operation::Multiply => 1.0,
        };
        let amounts = route
            .points()
            .iter()
            .map(|point| point.amount())
            .chain(weighted.contains(route.source()).then_some(neutral));
        let (minimum, maximum) = amounts.fold(
            (f64::INFINITY, f64::NEG_INFINITY),
            |(minimum, maximum), amount| (minimum.min(amount), maximum.max(amount)),
        );
        match route.operation() {
            Operation::Add => {
                low = quantity::finite(low + minimum)?;
                high = quantity::finite(high + maximum)?;
            }
            Operation::Multiply => multipliers.push((minimum, maximum)),
        }
    }
    for (minimum, maximum) in multipliers {
        let bounds = [low * minimum, low * maximum, high * minimum, high * maximum];
        low = quantity::finite(bounds.into_iter().fold(f64::INFINITY, f64::min))?;
        high = quantity::finite(bounds.into_iter().fold(f64::NEG_INFINITY, f64::max))?;
    }
    Ok((low, high))
}

/// Validate the composed instrument and effective slot ranges for both axes.
pub fn validate_sampler_spatial(
    instrument: &SoundSettings,
    slot: &SoundSettings,
) -> Result<(), Error> {
    for target in [SpatialTarget::Pan, SpatialTarget::StereoBalance] {
        let (instrument_low, instrument_high) = spatial_bounds(instrument, target)?;
        let (slot_low, slot_high) = spatial_bounds(slot, target)?;
        let low = instrument_low + slot_low;
        let high = instrument_high + slot_high;
        if low < -1.0 || high > 1.0 {
            return Err(invalid(format!(
                "combined {} range [{low}, {high}] exceeds [-1, 1]",
                target.parameter()
            )));
        }
    }
    Ok(())
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

pub(super) fn check_layout(channels: &[String]) -> Result<(), Error> {
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
