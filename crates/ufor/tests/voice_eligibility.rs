use serde_json::Value;
use ufor::codec::{self, Format};

#[test]
fn synth_mapping_matches_shared_cases() {
    let data: Value =
        serde_json::from_str(include_str!("../../../conformance/voice-eligibility.json")).unwrap();
    let text = data["voices"].to_string();
    let voices = codec::parse_voice_eligibility(&text, Format::Json, 6).unwrap();
    assert!(codec::parse_voice_eligibility(&text, Format::Json, 5).is_err());
    for case in data["cases"].as_array().unwrap() {
        let matches: Vec<_> = voices
            .matching_voices(
                serde_json::from_value(case["trigger"].clone()).unwrap(),
                case["key"].as_i64().unwrap(),
                case["velocity"].as_f64().unwrap(),
            )
            .map(|name| name.as_str())
            .collect();
        assert_eq!(serde_json::json!(matches), case["matches"], "{case}");
    }
}
