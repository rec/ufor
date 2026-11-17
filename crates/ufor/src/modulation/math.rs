//! Prepared scalar mappings and caller-owned accurate-sum storage.
//!
//! Construction may allocate. Evaluation and its fixed-size errors do not.
use super::{Interpolation, Point};
use crate::error::Error;
use std::fmt;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CalculationError {
    NonFinite,
    ScratchCapacity,
}

impl fmt::Display for CalculationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NonFinite => f.write_str("non-finite scalar arithmetic"),
            Self::ScratchCapacity => f.write_str("accurate-sum scratch capacity exceeded"),
        }
    }
}
impl std::error::Error for CalculationError {}

#[derive(Clone, Debug, PartialEq)]
pub struct Mapping {
    interpolation: Interpolation,
    points: Vec<Point>,
}

impl Mapping {
    /// Prepare a mapping. Document/operation record budgets belong to the caller.
    pub fn new(interpolation: Interpolation, points: Vec<Point>) -> Result<Self, Error> {
        validate(interpolation, &points)?;
        Ok(Self {
            interpolation,
            points,
        })
    }

    pub fn value(&self, value: f64) -> Result<f64, CalculationError> {
        map_points(self.interpolation, &self.points, value)
    }
}

/// Add one finite contribution, reserving at most one partial per contribution.
/// Supply storage for the maximum contribution count and initially set count=0.
/// After an arithmetic failure, discard this sum and start with count=0 again.
pub fn add_partial(
    partials: &mut [f64],
    count: &mut usize,
    mut value: f64,
) -> Result<(), CalculationError> {
    if *count >= partials.len() {
        return Err(CalculationError::ScratchCapacity);
    }
    finite(value)?;
    let mut index = 0;
    for j in 0..*count {
        let mut other = finite(partials[j])?;
        if value.abs() < other.abs() {
            std::mem::swap(&mut value, &mut other);
        }
        let hi = finite(value + other)?;
        let lo = other - (hi - value);
        if lo != 0.0 {
            partials[index] = lo;
            index += 1;
        }
        value = hi;
    }
    partials[index] = value;
    *count = index + 1;
    Ok(())
}

/// Finish the initialized prefix written by add_partial, including tie correction.
pub fn sum_partials(partials: &[f64]) -> Result<f64, CalculationError> {
    let Some((&last, rest)) = partials.split_last() else {
        return Ok(0.0);
    };
    let mut hi = finite(last)?;
    let mut lo = 0.0;
    let mut remaining = rest;
    while let Some((&y, rest)) = remaining.split_last() {
        let x = hi;
        hi = finite(x + finite(y)?)?;
        lo = y - (hi - x);
        remaining = rest;
        if lo != 0.0 {
            break;
        }
    }
    if remaining.last().is_some_and(|p| (*p < 0.0) == (lo < 0.0)) {
        let y = lo * 2.0;
        let x = hi + y;
        if x - hi == y {
            hi = x;
        }
    }
    finite(hi)
}

pub(super) fn validate(interpolation: Interpolation, points: &[Point]) -> Result<(), Error> {
    if points.is_empty()
        || points.windows(2).any(|p| p[1].input() <= p[0].input())
        || (interpolation == Interpolation::Exponential && points.iter().any(|p| p.amount() <= 0.0))
    {
        return Err(Error::Invalid("invalid mapping points".into()));
    }
    Ok(())
}

pub(super) fn map_points(
    interpolation: Interpolation,
    points: &[Point],
    value: f64,
) -> Result<f64, CalculationError> {
    finite(value)?;
    if value <= points[0].input() {
        return Ok(points[0].amount());
    }
    let index = points.partition_point(|p| p.input() <= value);
    let first = &points[index - 1];
    if index == points.len() || interpolation == Interpolation::Step {
        return Ok(first.amount());
    }
    let second = &points[index];
    let progress =
        finite(finite(value - first.input())? / finite(second.input() - first.input())?)?;
    finite(if interpolation == Interpolation::Exponential {
        finite(
            finite((1.0 - progress) * first.amount().ln())?
                + finite(progress * second.amount().ln())?,
        )?
        .exp()
    } else {
        first.amount() + finite(progress * finite(second.amount() - first.amount())?)?
    })
}

fn finite(value: f64) -> Result<f64, CalculationError> {
    if value.is_finite() {
        Ok(value)
    } else {
        Err(CalculationError::NonFinite)
    }
}
