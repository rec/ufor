//! Allocation-free pitch realization for oscillator and FM voices.

use crate::{error::Error, quantity};

/// Apply routed cents to the resolved onset pitch.
pub fn frequency(pitch_hz: f64, tuning_cents: f64) -> Result<f64, Error> {
    let frequency = quantity::finite(pitch_hz * 2_f64.powf(tuning_cents / 1200.0))?;
    if frequency <= 0.0 {
        return Err(Error::NonpositiveResult);
    }
    Ok(frequency)
}

/// Apply an FM operator ratio before the combined voice and operator tuning.
pub fn operator_frequency(
    pitch_hz: f64,
    ratio: f64,
    tuning_cents: f64,
    operator_cents: f64,
) -> Result<f64, Error> {
    frequency(pitch_hz * ratio, tuning_cents + operator_cents)
}
