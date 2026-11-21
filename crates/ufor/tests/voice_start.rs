use serde_json::Value;
use ufor::identifier::Identifier;
use ufor::voice_start::{envelfo_stream_key, prepare_values};

#[test]
fn voice_starts_match_shared_pitch_and_stream_vectors() {
    let vectors: Value =
        serde_json::from_str(include_str!("../../../conformance/voice-start.json")).unwrap();
    for spec in vectors["starts"].as_array().unwrap() {
        let voice = Identifier::new(spec["voice_id"].as_str().unwrap().to_owned()).unwrap();
        let result = prepare_values(
            spec["seed"].as_u64().unwrap(),
            &voice,
            spec["pitch_hz"].as_f64(),
            spec["frequency_offset_hz"].as_f64().unwrap(),
            spec["noise"].as_bool().unwrap(),
        )
        .unwrap();
        let expected = &spec["expected"];
        assert_eq!(result.pitch_hz, expected["pitch_hz"].as_f64());
        assert_eq!(result.noise_key, expected["noise_key"].as_u64());
        assert_eq!(result.envelfo_key, hex_key(&expected["envelfo_key"]));
        assert!(prepare_values(0, &voice, Some(f64::MAX), f64::MAX, false).is_err());
    }

    let graph = &vectors["graph_stream"];
    assert_eq!(
        envelfo_stream_key(
            graph["seed"].as_u64().unwrap(),
            graph["identity"].as_str().unwrap()
        ),
        hex_key(&graph["key"]),
    );
}

fn hex_key(value: &Value) -> u64 {
    u64::from_str_radix(value.as_str().unwrap(), 16).unwrap()
}
