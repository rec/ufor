//! Shared scalar envelope interpolation.

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
