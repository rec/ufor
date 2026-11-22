use ufor::envelope::curve_progress;

#[test]
fn shapes_progress_with_exact_endpoints_and_stable_extreme_curves() {
    for curve in [-1000.0, -2.0, 0.0, 2.0, 1000.0] {
        assert_eq!(curve_progress(0.0, curve), 0.0);
        assert_eq!(curve_progress(1.0, curve), 1.0);
    }
    assert_eq!(curve_progress(0.25, 0.0), 0.25);
    // At halfway, factoring exp(2) - 1 gives 1 / (1 + exp(1)).
    let upward = 1.0 / (1.0 + std::f64::consts::E);
    assert!((curve_progress(0.5, 2.0) - upward).abs() <= f64::EPSILON);
    assert!((curve_progress(0.5, -2.0) - (1.0 - upward)).abs() <= f64::EPSILON);
    let extreme = curve_progress(0.999, 1000.0);
    assert!((extreme - (-1.0_f64).exp()).abs() < 1e-14);
    assert_eq!(curve_progress(0.5, -1000.0), 1.0);
}
