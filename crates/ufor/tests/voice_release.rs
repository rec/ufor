use serde_json::{Value, json};
use ufor::codec::{self, Format};
use ufor::samples::controls::ControlDeclaration;
use ufor::voice_release::ReleasePlan;

#[test]
fn release_plans_match_shared_cases() {
    let data: Value =
        serde_json::from_str(include_str!("../../../conformance/voice-release.json")).unwrap();
    for case in data["cases"].as_array().unwrap() {
        let input = json!({"event": case["event"], "triggers": data["triggers"]}).to_string();
        let observed = codec::parse_voice_release(&input, Format::Json)
            .unwrap()
            .plan()
            .unwrap();
        let mut expected = serde_json::to_value(ReleasePlan::default()).unwrap();
        expected
            .as_object_mut()
            .unwrap()
            .extend(case["expected"].as_object().unwrap().clone());
        assert_eq!(
            serde_json::to_value(observed).unwrap(),
            expected,
            "{}",
            case["event"]
        );
    }
}

#[test]
fn initial_sustain_matches_shared_cases() {
    let data: Value =
        serde_json::from_str(include_str!("../../../conformance/voice-release.json")).unwrap();
    for case in data["initial_sustain"].as_array().unwrap() {
        let declaration: ControlDeclaration =
            serde_json::from_value(case["declaration"].clone()).unwrap();
        let observed =
            codec::parse_sustain(&case["sustain"].to_string(), Format::Json).and_then(|sustain| {
                let text = codec::sustain_text(&sustain, Format::Toml).unwrap();
                assert_eq!(codec::parse_sustain(&text, Format::Toml).unwrap(), sustain);
                sustain.initially_pressed(&declaration)
            });
        if case["invalid"] == true {
            assert!(observed.is_err(), "{case}");
        } else {
            assert_eq!(observed.unwrap(), case["pressed"].as_bool().unwrap());
        }
    }
}
