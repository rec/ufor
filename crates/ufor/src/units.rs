//! The shared tuning-specific unit subset; this is not a Pint replacement.

use crate::error::Error;
use crate::expression::evaluate_unit;

/// Normalize unit-bearing expressions to hertz, retaining unitless spelling.
pub fn frequency(text: &str) -> Result<String, Error> {
    let (value, has_unit) = evaluate_unit(text, FREQUENCIES)?;
    value.positive()?;
    Ok(if has_unit {
        value.to_string()
    } else {
        text.to_owned()
    })
}

/// Convert an authored detuning quantity to finite musical cents.
pub fn cents(text: &str) -> Result<f64, Error> {
    Ok(evaluate_unit(text, INTERVALS)?.0.as_f64())
}

const FREQUENCIES: &[(&str, i64, i64)] = &[
    ("Hz", 1, 1),
    ("hertz", 1, 1),
    ("kHz", 1000, 1),
    ("kilohertz", 1000, 1),
    ("mHz", 1, 1000),
    ("millihertz", 1, 1000),
    ("MHz", 1000000, 1),
    ("megahertz", 1000000, 1),
];
const INTERVALS: &[(&str, i64, i64)] = &[
    ("cent", 1, 1),
    ("cents", 1, 1),
    ("musical_cent", 1, 1),
    ("semitone", 100, 1),
    ("octave", 1200, 1),
    ("oct", 1200, 1),
];
