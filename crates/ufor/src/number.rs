//! Checked 64-bit rational and floating-point pitch arithmetic.

use crate::error::Error;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Rational {
    numerator: i64,
    denominator: i64,
}

impl Rational {
    pub fn new(numerator: i64, denominator: i64) -> Result<Self, Error> {
        Self::magnitudes(
            numerator.unsigned_abs(),
            denominator.unsigned_abs(),
            (numerator < 0) != (denominator < 0),
        )
    }

    fn magnitudes(n: u64, d: u64, negative: bool) -> Result<Self, Error> {
        if d == 0 {
            return Err(Error::DivisionByZero);
        }
        let common = gcd(n, d);
        Ok(Self {
            numerator: signed(n / common, negative)?,
            denominator: i64::try_from(d / common).map_err(|_| Error::ArithmeticRange)?,
        })
    }

    pub fn numerator(self) -> i64 {
        self.numerator
    }
    pub fn denominator(self) -> i64 {
        self.denominator
    }

    pub fn checked_add(self, other: Self) -> Result<Self, Error> {
        self.combine(other, i64::checked_add)
    }

    pub fn checked_sub(self, other: Self) -> Result<Self, Error> {
        self.combine(other, i64::checked_sub)
    }

    pub fn ceil(self) -> i64 {
        self.numerator.div_euclid(self.denominator)
            + i64::from(self.numerator.rem_euclid(self.denominator) != 0)
    }

    fn combine(self, other: Self, operation: fn(i64, i64) -> Option<i64>) -> Result<Self, Error> {
        let common = gcd(self.denominator as u64, other.denominator as u64) as i64;
        let left = self.denominator / common;
        let right = other.denominator / common;
        let first = self
            .numerator
            .checked_mul(right)
            .ok_or(Error::ArithmeticRange)?;
        let second = other
            .numerator
            .checked_mul(left)
            .ok_or(Error::ArithmeticRange)?;
        let numerator = operation(first, second).ok_or(Error::ArithmeticRange)?;
        let reduction = gcd(numerator.unsigned_abs(), common as u64) as i64;
        let denominator = left
            .checked_mul(other.denominator / reduction)
            .ok_or(Error::ArithmeticRange)?;
        Ok(Self {
            numerator: numerator / reduction,
            denominator,
        })
    }

    pub fn checked_mul(self, other: Self) -> Result<Self, Error> {
        let a = gcd(self.numerator.unsigned_abs(), other.denominator as u64);
        let b = gcd(other.numerator.unsigned_abs(), self.denominator as u64);
        let n = (self.numerator.unsigned_abs() / a)
            .checked_mul(other.numerator.unsigned_abs() / b)
            .ok_or(Error::ArithmeticRange)?;
        let d = (self.denominator as u64 / b)
            .checked_mul(other.denominator as u64 / a)
            .ok_or(Error::ArithmeticRange)?;
        Self::magnitudes(n, d, (self.numerator < 0) != (other.numerator < 0))
    }

    pub fn checked_div(self, other: Self) -> Result<Self, Error> {
        if other.numerator == 0 {
            return Err(Error::DivisionByZero);
        }
        let a = gcd(
            self.numerator.unsigned_abs(),
            other.numerator.unsigned_abs(),
        );
        let b = gcd(self.denominator as u64, other.denominator as u64);
        let n = (self.numerator.unsigned_abs() / a)
            .checked_mul(other.denominator as u64 / b)
            .ok_or(Error::ArithmeticRange)?;
        let d = (self.denominator as u64 / b)
            .checked_mul(other.numerator.unsigned_abs() / a)
            .ok_or(Error::ArithmeticRange)?;
        Self::magnitudes(n, d, (self.numerator < 0) != (other.numerator < 0))
    }

    pub fn checked_pow(self, exponent: i64) -> Result<Self, Error> {
        let mut base = if exponent < 0 {
            Self::new(self.denominator, self.numerator)?
        } else {
            self
        };
        let mut remaining = exponent.unsigned_abs();
        let mut value = Self::new(1, 1)?;
        while remaining != 0 {
            if remaining & 1 != 0 {
                value = value.checked_mul(base)?;
            }
            remaining >>= 1;
            if remaining != 0 {
                base = base.checked_mul(base)?;
            }
        }
        Ok(value)
    }

    pub fn from_f64(value: f64) -> Result<Self, Error> {
        if !value.is_finite() {
            return Err(Error::ArithmeticRange);
        }
        if value == 0.0 {
            return Self::new(0, 1);
        }
        let bits = value.to_bits();
        let encoded_exponent = ((bits >> 52) & 0x7ff) as i64;
        let mut mantissa = bits & ((1_u64 << 52) - 1);
        let mut exponent = if encoded_exponent == 0 {
            -1074
        } else {
            mantissa |= 1_u64 << 52;
            encoded_exponent - 1023 - 52
        };
        let zeros = mantissa.trailing_zeros();
        mantissa >>= zeros;
        exponent += i64::from(zeros);
        if exponent >= 0 {
            let shift = u32::try_from(exponent).map_err(|_| Error::ArithmeticRange)?;
            if shift >= 64 || mantissa > (u64::MAX >> shift) {
                return Err(Error::ArithmeticRange);
            }
            Self::magnitudes(mantissa << shift, 1, value.is_sign_negative())
        } else {
            let shift = u32::try_from(-exponent).map_err(|_| Error::ArithmeticRange)?;
            if shift >= 63 {
                return Err(Error::ArithmeticRange);
            }
            Self::magnitudes(mantissa, 1_u64 << shift, value.is_sign_negative())
        }
    }

    pub fn limit_denominator(self, maximum: i64) -> Result<Self, Error> {
        if maximum < 1 {
            return Err(Error::Invalid("denominator limit must be positive".into()));
        }
        if self.denominator <= maximum {
            return Ok(self);
        }
        // Equal-denominator ties at half-integers use floor, including negatives.
        if self.numerator < 0 && maximum == 1 && self.denominator == 2 {
            return Self::new(self.numerator.div_euclid(2), 1);
        }
        let negative = self.numerator < 0;
        let magnitude = self.numerator.unsigned_abs();
        // Start after the integer term. Since denominator > maximum >= 1,
        // both this quotient and remainder fit i64, even for i64::MIN.
        let integer = (magnitude / self.denominator as u64) as i64;
        let mut n = self.denominator;
        let mut d = (magnitude % self.denominator as u64) as i64;
        let (mut p0, mut q0, mut p1, mut q1) = (1_i64, 0_i64, integer, 1_i64);
        loop {
            let a = n / d;
            let q2 = a.checked_mul(q1).and_then(|v| q0.checked_add(v));
            if q2.is_none_or(|v| v > maximum) {
                break;
            }
            let p2 = a
                .checked_mul(p1)
                .and_then(|v| p0.checked_add(v))
                .ok_or(Error::ArithmeticRange)?;
            (p0, q0, p1, q1) = (p1, q1, p2, q2.ok_or(Error::ArithmeticRange)?);
            (n, d) = (d, n % d);
            if d == 0 {
                return Self::new(if negative { -p1 } else { p1 }, q1);
            }
        }
        let k = (maximum - q0) / q1;
        let p = k
            .checked_mul(p1)
            .and_then(|v| p0.checked_add(v))
            .ok_or(Error::ArithmeticRange)?;
        let q = k
            .checked_mul(q1)
            .and_then(|v| q0.checked_add(v))
            .ok_or(Error::ArithmeticRange)?;
        let first = Self::new(p, q)?;
        let second = Self::new(p1, q1)?;
        // In the continued-fraction tail t = n/d, the second bound is
        // closest exactly when t - k >= q/q1. Compare those fractions
        // directly, avoiding the large cross-products of two distances.
        let remainder = Self::new(n - k * d, d)?;
        let threshold = Self::new(q, q1)?;
        let selected = if remainder.cmp(&threshold) != std::cmp::Ordering::Less {
            second
        } else {
            first
        };
        Self::new(
            if negative {
                -selected.numerator
            } else {
                selected.numerator
            },
            selected.denominator,
        )
    }
}

impl From<i64> for Rational {
    fn from(numerator: i64) -> Self {
        Self {
            numerator,
            denominator: 1,
        }
    }
}

impl std::fmt::Display for Rational {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        if self.denominator == 1 {
            write!(f, "{}", self.numerator)
        } else {
            write!(f, "{}/{}", self.numerator, self.denominator)
        }
    }
}

impl PartialOrd for Rational {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for Rational {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        if (self.numerator < 0) != (other.numerator < 0) {
            return self.numerator.cmp(&other.numerator);
        }
        let (mut a, mut b, mut c, mut d) = (
            self.numerator.unsigned_abs(),
            self.denominator as u64,
            other.numerator.unsigned_abs(),
            other.denominator as u64,
        );
        let mut reversed = self.numerator < 0;
        loop {
            let order = (a / b).cmp(&(c / d));
            let (r, s) = (a % b, c % d);
            let order = if order != std::cmp::Ordering::Equal {
                order
            } else if r == 0 || s == 0 {
                r.cmp(&s)
            } else {
                (a, b, c, d) = (b, r, d, s);
                reversed = !reversed;
                continue;
            };
            return if reversed { order.reverse() } else { order };
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Number(Value);

#[derive(Clone, Copy, Debug, PartialEq)]
enum Value {
    Exact(Rational),
    Approx(f64),
}

impl Number {
    pub fn exact(numerator: i64, denominator: i64) -> Result<Self, Error> {
        Ok(Self(Value::Exact(Rational::new(numerator, denominator)?)))
    }

    pub fn approximate(value: f64) -> Result<Self, Error> {
        if !value.is_finite() {
            return Err(Error::ArithmeticRange);
        }
        Ok(Self(Value::Approx(value)))
    }

    pub fn rational(self) -> Option<Rational> {
        match self.0 {
            Value::Exact(value) => Some(value),
            Value::Approx(_) => None,
        }
    }

    pub fn as_f64(self) -> f64 {
        match self.0 {
            Value::Exact(value) => value.numerator as f64 / value.denominator as f64,
            Value::Approx(value) => value,
        }
    }

    pub fn positive(self) -> Result<Self, Error> {
        if self.as_f64() <= 0.0 {
            Err(Error::NonpositiveResult)
        } else {
            Ok(self)
        }
    }

    pub fn checked_neg(self) -> Result<Self, Error> {
        match self.0 {
            Value::Exact(value) => Self::exact(
                value
                    .numerator
                    .checked_neg()
                    .ok_or(Error::ArithmeticRange)?,
                value.denominator,
            ),
            Value::Approx(value) => Self::approximate(-value),
        }
    }

    pub fn checked_mul(self, other: Self) -> Result<Self, Error> {
        match (self.0, other.0) {
            (Value::Exact(a), Value::Exact(b)) => Ok(Self(Value::Exact(a.checked_mul(b)?))),
            _ => Self::approximate(self.as_f64() * other.as_f64()),
        }
    }

    pub fn checked_div(self, other: Self) -> Result<Self, Error> {
        if other.as_f64() == 0.0 {
            return Err(Error::DivisionByZero);
        }
        match (self.0, other.0) {
            (Value::Exact(a), Value::Exact(b)) => Ok(Self(Value::Exact(a.checked_div(b)?))),
            _ => Self::approximate(self.as_f64() / other.as_f64()),
        }
    }

    pub fn checked_pow(self, exponent: Self) -> Result<Self, Error> {
        if let Value::Exact(e) = exponent.0 {
            if e.denominator == 1 {
                return match self.0 {
                    Value::Exact(value) => Ok(Self(Value::Exact(value.checked_pow(e.numerator)?))),
                    Value::Approx(value) => Self::approximate(value.powf(e.numerator as f64)),
                };
            }
        }
        if self.as_f64() < 0.0 {
            return Err(Error::Invalid("fractional power of negative base".into()));
        }
        Self::approximate(self.as_f64().powf(exponent.as_f64()))
    }

    pub fn limit_denominator(self, maximum: i64) -> Result<Self, Error> {
        let rational = match self.0 {
            Value::Exact(value) => value,
            Value::Approx(value) => Rational::from_f64(value)?,
        };
        Ok(Self(Value::Exact(rational.limit_denominator(maximum)?)))
    }
}

impl std::fmt::Display for Number {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self.0 {
            Value::Exact(value) => write!(f, "{value}"),
            Value::Approx(value) => write!(f, "{value:?}"),
        }
    }
}

fn gcd(mut a: u64, mut b: u64) -> u64 {
    while b != 0 {
        (a, b) = (b, a % b);
    }
    a
}

fn signed(value: u64, negative: bool) -> Result<i64, Error> {
    if negative && value == 1_u64 << 63 {
        return Ok(i64::MIN);
    }
    let value = i64::try_from(value).map_err(|_| Error::ArithmeticRange)?;
    Ok(if negative { -value } else { value })
}
