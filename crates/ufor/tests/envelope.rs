use serde::Deserialize;
use serde_json::Value;
use ufor::codec::{Format, curve_text, parse_curve};
use ufor::envelfo::PreparationLimits;
use ufor::envelope::curve_progress;
use ufor::quantity::exact;

#[test]
fn evaluates_and_round_trips_shared_envelope_curves() {
    #[derive(Deserialize)]
    struct Fixture {
        cases: Vec<Case>,
    }
    #[derive(Deserialize)]
    struct Case {
        name: String,
        curve: Value,
        queries: Vec<Query>,
    }
    #[derive(Deserialize)]
    struct Query {
        at: String,
        value: f64,
    }

    let fixture: Fixture =
        serde_json::from_str(include_str!("../../../conformance/envelope-curves.json")).unwrap();
    let limits = PreparationLimits::default();
    for case in fixture.cases {
        let curve = parse_curve(&case.curve.to_string(), Format::Json, limits).unwrap();
        for query in case.queries {
            let actual = curve.at(exact(&query.at, "ratio").unwrap()).unwrap();
            assert!(
                (actual - query.value).abs() <= 1e-14,
                "{} at {}",
                case.name,
                query.at
            );
        }
        for format in [Format::Json, Format::Toml] {
            let encoded = curve_text(&curve, format).unwrap();
            assert_eq!(parse_curve(&encoded, format, limits).unwrap(), curve);
        }
    }
}

#[test]
fn rejects_empty_curves_zero_periods_and_negative_positions() {
    let limits = PreparationLimits::default();
    assert!(parse_curve(r#"{"segments":[]}"#, Format::Json, limits).is_err());
    let zero_period = r#"{"segments":[{"duration":0,"to":1}],"repeat":true}"#;
    assert!(parse_curve(zero_period, Format::Json, limits).is_err());
    let curve = r#"{"segments":[{"duration":1,"to":1}]}"#;
    assert!(parse_curve(curve, Format::Json, PreparationLimits::new(1).unwrap()).is_err());
    let curve = parse_curve(curve, Format::Json, limits).unwrap();
    assert!(curve.at((-1).into()).is_err());
}

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
