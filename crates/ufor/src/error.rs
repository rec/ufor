//! Errors at the portable definition and arithmetic boundaries.

use std::fmt;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    Invalid(String),
    ArithmeticRange,
    DivisionByZero,
    NonpositiveResult,
    OutsideDomain,
    Limit(&'static str),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(message) => write!(f, "{message}"),
            Self::ArithmeticRange => write!(f, "arithmetic exceeds the 64-bit domain"),
            Self::DivisionByZero => write!(f, "division by zero"),
            Self::NonpositiveResult => write!(f, "tuning result must be positive"),
            Self::OutsideDomain => write!(f, "note is outside the finite source domain"),
            Self::Limit(name) => write!(f, "{name} limit exceeded"),
        }
    }
}

impl std::error::Error for Error {}
