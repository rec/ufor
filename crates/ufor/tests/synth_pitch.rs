use serde_json::Value;
use ufor::synth_pitch::{frequency, operator_frequency};

#[test]
fn rendered_pitches_match_shared_vectors() {
    let vectors: Value =
        serde_json::from_str(include_str!("../../../conformance/synth-pitch.json")).unwrap();
    for spec in vectors["frequency"].as_array().unwrap() {
        let [pitch, cents, expected] = numbers(spec);
        assert!((frequency(pitch, cents).unwrap() - expected).abs() <= 1e-12);
    }
    for spec in vectors["operator"].as_array().unwrap() {
        let [pitch, ratio, cents, operator_cents, expected] = numbers(spec);
        let frequency = operator_frequency(pitch, ratio, cents, operator_cents).unwrap();
        assert!((frequency - expected).abs() <= 1e-12);
    }
    for spec in vectors["invalid_frequency"].as_array().unwrap() {
        let [pitch, cents] = numbers(spec);
        assert!(frequency(pitch, cents).is_err());
    }
}

fn numbers<const N: usize>(value: &Value) -> [f64; N] {
    std::array::from_fn(|index| value[index].as_f64().unwrap())
}
