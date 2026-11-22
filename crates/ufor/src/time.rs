//! Physical tick rates and exact conversion between native coordinates.

use crate::{error::Error, identifier::Identifier};
use serde::{Deserialize, Serialize};

/// A positive declared rate. The denominator is kept as authored.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(try_from = "RateDefinition")]
pub struct Rate {
    numerator: i64,
    denominator: i64,
}

impl Rate {
    pub fn new(numerator: i64, denominator: i64) -> Result<Self, Error> {
        if numerator <= 0 || denominator <= 0 {
            return Err(Error::Invalid("Timebase rate must be positive".into()));
        }
        Ok(Self {
            numerator,
            denominator,
        })
    }

    pub fn numerator(self) -> i64 {
        self.numerator
    }

    pub fn denominator(self) -> i64 {
        self.denominator
    }

    /// Return the declared integer rate for renderers with denominator one.
    pub fn integer_hz(self) -> Option<i64> {
        (self.denominator == 1).then_some(self.numerator)
    }
}

/// Named physical timebase, matching the portable declaration.
#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Timebase {
    name: Identifier,
    #[serde(default)]
    kind: TimebaseKind,
    rate: Rate,
}

impl Timebase {
    pub fn new(name: Identifier, rate: Rate) -> Self {
        Self {
            name,
            kind: TimebaseKind::Physical,
            rate,
        }
    }

    pub fn name(&self) -> &Identifier {
        &self.name
    }

    pub fn rate(&self) -> Rate {
        self.rate
    }
}

/// Convert an absolute tick exactly, rounding once to nearest with ties to even.
pub fn convert_tick(tick: i64, source: &Timebase, destination: &Timebase) -> Result<i64, Error> {
    let left = tick.unsigned_abs() as u128 * source.rate.denominator as u128;
    let right = destination.rate.numerator as u128;
    let divisor = source.rate.numerator as u128 * destination.rate.denominator as u128;
    let (quotient, remainder) = divide_product(left, right, divisor)?;
    let round_up = remainder * 2 > divisor || (remainder * 2 == divisor && quotient % 2 != 0);
    let magnitude = quotient
        .checked_add(u128::from(round_up))
        .and_then(|value| i128::try_from(value).ok())
        .ok_or(Error::ArithmeticRange)?;
    i64::try_from(if tick < 0 { -magnitude } else { magnitude }).map_err(|_| Error::ArithmeticRange)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RateDefinition {
    numerator: i64,
    #[serde(default = "one")]
    denominator: i64,
}

impl TryFrom<RateDefinition> for Rate {
    type Error = Error;

    fn try_from(value: RateDefinition) -> Result<Self, Error> {
        Self::new(value.numerator, value.denominator)
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum TimebaseKind {
    #[default]
    Physical,
}

fn one() -> i64 {
    1
}

fn divide_product(left: u128, right: u128, divisor: u128) -> Result<(u128, u128), Error> {
    if let Some(product) = left.checked_mul(right) {
        return Ok((product / divisor, product % divisor));
    }
    let whole = (left / divisor)
        .checked_mul(right)
        .ok_or(Error::ArithmeticRange)?;
    let part = left % divisor;
    let mut quotient = 0;
    let mut remainder = 0;
    // Divide the fractional part of left / divisor as each multiplier bit
    // arrives. The divisor is a product of two positive i64 values, so
    // doubling the remainder and adding part both fit in u128.
    for bit in (0..=right.ilog2()).rev() {
        remainder *= 2;
        if right & (1 << bit) != 0 {
            remainder += part;
        }
        quotient = quotient * 2 + remainder / divisor;
        remainder %= divisor;
    }
    Ok((
        whole.checked_add(quotient).ok_or(Error::ArithmeticRange)?,
        remainder,
    ))
}
