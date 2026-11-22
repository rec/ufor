//! Autonomous scalar envelope curves and shared segment interpolation.

use crate::envelfo::Segment;
use crate::error::Error;
use crate::number::Rational;
use crate::quantity::finite;
use serde::{Deserialize, Serialize};

/// A finite scalar initial level followed by one or more shared segments.
#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(try_from = "CurveDefinition")]
pub struct Curve {
    initial: f64,
    segments: Vec<Segment>,
    repeat: bool,
    #[serde(skip)]
    period: Option<Rational>,
}

impl Curve {
    pub fn new(initial: f64, segments: Vec<Segment>, repeat: bool) -> Result<Self, Error> {
        finite(initial)?;
        if segments.is_empty() {
            return Err(Error::Invalid("curve requires at least one segment".into()));
        }
        let period = if repeat {
            let total = segments
                .iter()
                .try_fold(Rational::from(0), |sum, segment| {
                    sum.checked_add(segment.duration())
                })?;
            if total.numerator() == 0 {
                return Err(Error::Invalid(
                    "repeating curve requires a positive period".into(),
                ));
            }
            Some(total)
        } else {
            None
        };
        Ok(Self {
            initial,
            segments,
            repeat,
            period,
        })
    }

    pub fn segments(&self) -> &[Segment] {
        &self.segments
    }

    /// Evaluate at a nonnegative rational distance from activation, using the
    /// authored duration magnitudes. Clock conversion belongs to the caller.
    pub fn at(&self, mut elapsed: Rational) -> Result<f64, Error> {
        if elapsed.numerator() < 0 {
            return Err(Error::Invalid("curve position precedes activation".into()));
        }
        if let Some(period) = self.period {
            elapsed = elapsed.checked_rem(period)?;
        }
        let mut value = self.initial;
        for segment in &self.segments {
            let duration = segment.duration();
            let end = segment.to().value();
            if elapsed < duration {
                let progress = elapsed.checked_div(duration)?.to_f64();
                return finite(value + (end - value) * curve_progress(progress, segment.curve()));
            }
            elapsed = elapsed.checked_sub(duration)?;
            value = end;
        }
        Ok(value)
    }
}

/// Shape normalized segment progress with a signed exponential curve.
///
/// The caller supplies progress in `[0, 1]` and a finite curve coefficient.
/// A zero coefficient gives linear progress. Both endpoints are exact.
#[inline]
pub fn curve_progress(progress: f64, curve: f64) -> f64 {
    if curve == 0.0 || progress == 0.0 || progress == 1.0 {
        return progress;
    }
    if curve > 0.0 {
        (curve * (progress - 1.0)).exp() * (-curve * progress).exp_m1() / (-curve).exp_m1()
    } else {
        (curve * progress).exp_m1() / curve.exp_m1()
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CurveDefinition {
    #[serde(default)]
    initial: f64,
    segments: Vec<Segment>,
    #[serde(default)]
    repeat: bool,
}

impl TryFrom<CurveDefinition> for Curve {
    type Error = Error;

    fn try_from(value: CurveDefinition) -> Result<Self, Error> {
        Self::new(value.initial, value.segments, value.repeat)
    }
}
