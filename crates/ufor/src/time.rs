//! Physical tick rates and exact conversion between native coordinates.

use crate::number::Rational;
use crate::{error::Error, identifier::Identifier};
use serde::{Deserialize, Serialize};

/// Convert nonnegative seconds to an exact fractional frame duration.
pub fn duration_frames(seconds: Rational, sample_rate: i64) -> Result<Rational, Error> {
    if seconds.numerator() < 0 || sample_rate <= 0 {
        return Err(Error::Invalid(
            "frame duration requires nonnegative seconds and a positive sample rate".into(),
        ));
    }
    seconds.checked_mul(sample_rate.into())
}

/// Nonempty half-open interval in native ticks.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(try_from = "TickRangeDefinition")]
pub struct TickRange {
    start: i64,
    end: i64,
}

impl TickRange {
    pub fn new(start: i64, end: i64) -> Result<Self, Error> {
        if end <= start {
            return Err(Error::Invalid("end must be greater than start".into()));
        }
        Ok(Self { start, end })
    }

    pub fn start(self) -> i64 {
        self.start
    }

    pub fn end(self) -> i64 {
        self.end
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TickRangeDefinition {
    start: i64,
    end: i64,
}

impl TryFrom<TickRangeDefinition> for TickRange {
    type Error = Error;

    fn try_from(value: TickRangeDefinition) -> Result<Self, Error> {
        Self::new(value.start, value.end)
    }
}

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
    let magnitude =
        i128::try_from(round_product(left, right, divisor)?).map_err(|_| Error::ArithmeticRange)?;
    i64::try_from(if tick < 0 { -magnitude } else { magnitude }).map_err(|_| Error::ArithmeticRange)
}

/// Convert an unsigned distance between native ticks, requiring an exact result.
pub(crate) fn convert_exact_distance(
    ticks: u64,
    source: Rate,
    destination: Rate,
) -> Result<u64, Error> {
    let left = u128::from(ticks) * source.denominator as u128;
    let right = destination.numerator as u128;
    let divisor = source.numerator as u128 * destination.denominator as u128;
    let (quotient, remainder) = divide_product(left, right, divisor)?;
    if remainder != 0 {
        return Err(Error::Invalid(
            "converted distance is not an exact integer tick".into(),
        ));
    }
    u64::try_from(quotient).map_err(|_| Error::ArithmeticRange)
}

/// Exact frame clock for an ordered sequence of PPQN MIDI file events.
#[derive(Clone, Debug)]
pub struct PpqnClock {
    tick: i64,
    elapsed: u128,
    tempo: u32,
    sample_rate: i64,
    divisor: u128,
}

impl PpqnClock {
    pub fn new(ticks_per_quarter: u16, sample_rate: i64) -> Result<Self, Error> {
        if !(1..=0x7fff).contains(&ticks_per_quarter) || sample_rate <= 0 {
            return Err(Error::Invalid(
                "MIDI requires positive PPQN and integer sample rate".into(),
            ));
        }
        Ok(Self {
            tick: 0,
            elapsed: 0,
            tempo: 500_000,
            sample_rate,
            divisor: u128::from(ticks_per_quarter) * 1_000_000,
        })
    }

    /// Round the absolute event position to a frame. A tempo at this tick
    /// applies only to intervals that follow it.
    pub fn advance(&mut self, tick: i64, next_tempo: Option<u32>) -> Result<i64, Error> {
        if tick < self.tick {
            return Err(Error::Invalid("MIDI ticks must not move backward".into()));
        }
        if next_tempo.is_some_and(|tempo| tempo > 0xff_ffff) {
            return Err(Error::Invalid("MIDI tempo exceeds 24 bits".into()));
        }
        // The carried numerator is bounded by the current i64 tick times
        // the largest 24-bit tempo, regardless of the number of segments.
        let elapsed = self.elapsed + (tick - self.tick) as u128 * u128::from(self.tempo);
        let frame = i64::try_from(round_product(
            elapsed,
            self.sample_rate as u128,
            self.divisor,
        )?)
        .map_err(|_| Error::ArithmeticRange)?;
        self.tick = tick;
        self.elapsed = elapsed;
        self.tempo = next_tempo.unwrap_or(self.tempo);
        Ok(frame)
    }
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

fn round_product(left: u128, right: u128, divisor: u128) -> Result<u128, Error> {
    let (quotient, remainder) = divide_product(left, right, divisor)?;
    let round_up = remainder * 2 > divisor || (remainder * 2 == divisor && quotient % 2 != 0);
    quotient
        .checked_add(u128::from(round_up))
        .ok_or(Error::ArithmeticRange)
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
