//! Portable oscillator declarations and scalar shape mathematics.

use crate::number::{binary_parts, round_binary_ratio};
use crate::{envelfo::Waveform, error::Error, number::Rational, quantity};
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::Value;
use std::f64::consts::TAU;

/// Transport position in output frames, before conversion to oscillator phase.
#[derive(Clone, Copy, Debug)]
pub enum PhaseOrigin {
    Whole(i64),
    Fractional(f64),
}

/// Compute the exact product modulo the sample rate, rounded once to binary64.
/// The returned phase is in sample-rate units.
pub fn phase_at_frame(
    origin: PhaseOrigin,
    frequency_hz: f64,
    sample_rate: i64,
) -> Result<f64, Error> {
    if sample_rate <= 0 {
        return Err(Error::NonpositiveResult);
    }
    let frequency_hz = quantity::finite(frequency_hz)?;
    let (frame, exponent, negative) = match origin {
        PhaseOrigin::Whole(frame) => (frame.unsigned_abs(), 0, frame < 0),
        PhaseOrigin::Fractional(frame) => {
            let frame = quantity::finite(frame)?;
            let (significand, exponent) = binary_parts(frame);
            (significand, exponent, frame.is_sign_negative())
        }
    };
    let (frequency, frequency_exponent) = binary_parts(frequency_hz);
    let numerator = u128::from(frame) * u128::from(frequency);
    let negative = negative ^ frequency_hz.is_sign_negative();
    Ok(wrap_phase(
        numerator,
        exponent + frequency_exponent,
        sample_rate as u128,
        negative,
    ))
}

fn wrap_phase(numerator: u128, exponent: i32, rate: u128, negative: bool) -> f64 {
    if numerator == 0 {
        return 0.0;
    }
    if exponent >= 0 {
        let mut remainder = numerator % rate;
        for _ in 0..exponent {
            remainder = (remainder << 1) % rate;
        }
        return if negative && remainder != 0 {
            rate - remainder
        } else {
            remainder
        } as f64;
    }
    let shift = exponent.unsigned_abs();
    if shift <= rate.leading_zeros() {
        let modulus = rate << shift;
        let remainder = numerator % modulus;
        let wrapped = if negative && remainder != 0 {
            modulus - remainder
        } else {
            remainder
        };
        return round_binary_ratio(wrapped, 1, exponent);
    }
    // The full modulus exceeds u128, so the numerator is already reduced.
    if !negative {
        return round_binary_ratio(numerator, 1, exponent);
    }
    // For the negative case, retain 127 high bits and whether any lower bit
    // was set. The result is close to rate, so binary64 rounding midpoints
    // are on the retained grid. Any interior point of the final bin rounds
    // the same way as the exact result.
    let retained = rate.leading_zeros() - 1;
    let dropped = shift - retained;
    let high = numerator.checked_shr(dropped).unwrap_or(0);
    let complement = (rate << retained) - high;
    if high.checked_shl(dropped) == Some(numerator) {
        round_binary_ratio(complement, 1, -(retained as i32))
    } else {
        round_binary_ratio((complement << 1) - 1, 1, -(retained as i32) - 1)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Oscillator {
    waveform: Waveform,
    #[serde(serialize_with = "write_ratio", deserialize_with = "duty")]
    duty_cycle: Rational,
    key_scale_note: i64,
    #[serde(deserialize_with = "decibels")]
    key_scale_db_per_12_steps: f64,
}

impl Default for Oscillator {
    fn default() -> Self {
        Self {
            waveform: Waveform::Triangle,
            duty_cycle: Rational::new(1, 2).expect("one half"),
            key_scale_note: 64,
            key_scale_db_per_12_steps: 0.0,
        }
    }
}

impl Oscillator {
    pub fn waveform(&self) -> Waveform {
        self.waveform
    }

    pub fn duty_cycle(&self) -> Rational {
        self.duty_cycle
    }

    /// Round the exact duty cycle to the renderer's binary64 value.
    pub fn duty_cycle_f64(&self) -> f64 {
        self.duty_cycle.to_f64()
    }

    /// Convert authored dB per octave into a linear gain at this note.
    pub fn gain(&self, note_number: i64) -> Result<f64, Error> {
        let distance = note_number.abs_diff(self.key_scale_note) as f64;
        let steps = if note_number < self.key_scale_note {
            -distance
        } else {
            distance
        };
        quantity::finite(10_f64.powf(self.key_scale_db_per_12_steps * steps / 12.0 / 20.0))
    }
}

/// Evaluate one shape observation for an exact phase and duty cycle.
pub fn shape_value(
    waveform: Waveform,
    phase: Rational,
    duty_cycle: Rational,
) -> Result<f64, Error> {
    if !(0.into()..1.into()).contains(&phase) || !(0.into()..=1.into()).contains(&duty_cycle) {
        return Err(Error::Invalid(
            "shape requires phase in [0, 1) and duty in [0, 1]".into(),
        ));
    }
    match waveform {
        Waveform::Sine => Ok((TAU * phase.to_f64()).sin()),
        Waveform::Square => Ok(if phase < duty_cycle { 1.0 } else { -1.0 }),
        Waveform::Triangle => {
            let twice = phase.checked_mul(2.into())?;
            let value = if phase < duty_cycle {
                twice.checked_div(duty_cycle)?.checked_sub(1.into())?
            } else {
                Rational::from(1)
                    .checked_add(duty_cycle)?
                    .checked_sub(twice)?
                    .checked_div(Rational::from(1).checked_sub(duty_cycle)?)?
            };
            Ok(value.to_f64())
        }
    }
}

fn write_ratio<S: Serializer>(value: &Rational, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.collect_str(value)
}

fn duty<'de, D: Deserializer<'de>>(d: D) -> Result<Rational, D::Error> {
    let text = match Value::deserialize(d)? {
        Value::Number(value) => value.to_string(),
        Value::String(value) => value,
        _ => return Err(serde::de::Error::custom("duty_cycle must be numeric")),
    };
    let ratio = quantity::exact(&text, "ratio").map_err(serde::de::Error::custom)?;
    if !(0.into()..=1.into()).contains(&ratio) {
        return Err(serde::de::Error::custom("duty_cycle must be in [0, 1]"));
    }
    Ok(ratio)
}

fn decibels<'de, D: Deserializer<'de>>(d: D) -> Result<f64, D::Error> {
    quantity::deserialize_scalar(d, "db")
}
