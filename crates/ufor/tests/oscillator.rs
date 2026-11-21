use serde_json::Value;
use ufor::codec::{self, Format};
use ufor::oscillator::shape_value;
use ufor::quantity;

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
