use serde_json::Value;
use ufor::codec::{self, Format};
use ufor::envelfo::PreparationLimits;
use ufor::oscillator::{PhaseOrigin, phase_at_frame, shape_value};
use ufor::quantity;
use ufor::score::Score;

#[test]
fn transport_phase_reduces_the_exact_product_before_rounding() {
    let phase = |origin, frequency, rate| phase_at_frame(origin, frequency, rate).unwrap();
    assert_eq!(phase(PhaseOrigin::Whole((1 << 53) + 1), 0.5, 4), 0.5);
    assert_eq!(phase(PhaseOrigin::Whole(-(1 << 53) - 1), 0.5, 4), 3.5);
    assert_eq!(phase(PhaseOrigin::Fractional(-0.5), 3.0, 10), 8.5);
    let huge = 2.0_f64.powi(900);
    assert_eq!(phase(PhaseOrigin::Fractional(huge), huge, 3), 1.0);
    let subnormal = f64::from_bits(1);
    assert_eq!(phase(PhaseOrigin::Fractional(subnormal), 0.5, 3), 0.0);
    assert_eq!(phase(PhaseOrigin::Fractional(-subnormal), 0.5, 3), 3.0);
    assert!(phase_at_frame(PhaseOrigin::Whole(1), f64::INFINITY, 48_000).is_err());
}

#[test]
fn declarations_and_shapes_match_shared_vectors() {
    let vectors: Value =
        serde_json::from_str(include_str!("../../../conformance/oscillator.json")).unwrap();
    for spec in vectors["definitions"].as_array().unwrap() {
        let oscillator =
            codec::parse_oscillator(&spec["oscillator"].to_string(), Format::Json).unwrap();
        assert_eq!(
            serde_json::to_value(oscillator.waveform()).unwrap(),
            spec["waveform"]
        );
        assert_eq!(
            oscillator.duty_cycle().to_string(),
            spec["duty"].as_str().unwrap()
        );
        assert_eq!(
            oscillator.duty_cycle_f64(),
            spec["duty_f64"].as_f64().unwrap()
        );
        for gain in spec["gains"].as_array().unwrap() {
            let actual = oscillator.gain(gain[0].as_i64().unwrap()).unwrap();
            assert!((actual - gain[1].as_f64().unwrap()).abs() < 1e-14);
        }
        for format in [Format::Json, Format::Toml] {
            let text = codec::oscillator_text(&oscillator, format).unwrap();
            assert_eq!(codec::parse_oscillator(&text, format).unwrap(), oscillator);
        }
    }
    for spec in vectors["shape"].as_array().unwrap() {
        let waveform = serde_json::from_value(spec[0].clone()).unwrap();
        let phase = quantity::exact(spec[1].as_str().unwrap(), "ratio").unwrap();
        let duty = quantity::exact(spec[2].as_str().unwrap(), "ratio").unwrap();
        assert_eq!(
            shape_value(waveform, phase, duty).unwrap(),
            spec[3].as_f64().unwrap()
        );
    }
    for duty in vectors["invalid_duties"].as_array().unwrap() {
        let text = serde_json::json!({"duty_cycle": duty}).to_string();
        assert!(codec::parse_oscillator(&text, Format::Json).is_err());
    }
}

#[test]
fn oscillator_score_preserves_its_header_and_exact_body() {
    let vectors: Value =
        serde_json::from_str(include_str!("../../../conformance/oscillator.json")).unwrap();
    let input = &vectors["score"];
    let limits = PreparationLimits::default();
    let score = codec::parse_score(&input.to_string(), Format::Json, limits).unwrap();
    let Score::Oscillator(oscillator) = &score else {
        panic!("expected oscillator score");
    };
    assert_eq!(score.name(), "asymmetric pulse");
    assert_eq!(score.title(), "Asymmetric pulse");
    assert_eq!(score.tags(), ["#oscillator", "#square"]);
    assert_eq!(
        oscillator.body().duty_cycle().to_string(),
        input["body"]["duty_cycle"].as_str().unwrap()
    );
    assert_eq!(oscillator.body().gain(72).unwrap(), 10.0);
    for format in [Format::Json, Format::Toml] {
        let text = codec::score_text(&score, format).unwrap();
        assert_eq!(codec::parse_score(&text, format, limits).unwrap(), score);
    }
    for overrides in vectors["invalid_score_overrides"].as_array().unwrap() {
        let mut document = input.clone();
        document
            .as_object_mut()
            .unwrap()
            .extend(overrides.as_object().unwrap().clone());
        assert!(
            codec::parse_score(&document.to_string(), Format::Json, limits).is_err(),
            "{overrides}"
        );
    }
}
