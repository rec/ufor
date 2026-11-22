use serde_json::{Value, json};
use ufor::codec::{self, Format};
use ufor::envelfo::PreparationLimits;
use ufor::number::Rational;

#[test]
fn synth_mapping_matches_shared_cases() {
    let data: Value =
        serde_json::from_str(include_str!("../../../conformance/voice-eligibility.json")).unwrap();
    let text = data["voices"].to_string();
    let voices = codec::parse_voice_eligibility(&text, Format::Json, 6).unwrap();
    assert!(codec::parse_voice_eligibility(&text, Format::Json, 5).is_err());
    let fields = data["template_fields"].as_object().unwrap();
    let definitions: Vec<_> = data["voices"]
        .as_array()
        .unwrap()
        .iter()
        .map(|voice| {
            let mut voice = voice.as_object().unwrap().clone();
            voice.extend(fields.clone());
            voice
        })
        .collect();
    let document = json!({"voices":definitions});
    let limits = PreparationLimits::new(25).unwrap();
    let templates =
        codec::parse_synth_voice_templates(&document.to_string(), Format::Json, limits).unwrap();
    assert!(
        codec::parse_synth_voice_templates(
            &document.to_string(),
            Format::Json,
            PreparationLimits::new(24).unwrap(),
        )
        .is_err()
    );
    let voice = &templates.voices()[0];
    assert_eq!(voice.channels()[0].output, "left");
    assert_eq!(voice.frequency_offset_hz(), 1000.0);
    assert_eq!(
        voice.minimum_hold_seconds(),
        Rational::new(1, 32000).unwrap()
    );
    assert_eq!(voice.chokes()[0].fade_seconds(), Some(0.125));
    let text = toml::to_string(&templates).unwrap();
    let restored = codec::parse_synth_voice_templates(&text, Format::Toml, limits).unwrap();
    assert_eq!(
        serde_json::to_value(restored).unwrap(),
        serde_json::to_value(&templates).unwrap()
    );
    for case in data["cases"].as_array().unwrap() {
        let trigger = serde_json::from_value(case["trigger"].clone()).unwrap();
        let key = case["key"].as_i64().unwrap();
        let velocity = case["velocity"].as_f64().unwrap();
        let matches: Vec<_> = voices
            .matching_voices(trigger, key, velocity)
            .map(|name| name.as_str())
            .collect();
        assert_eq!(serde_json::json!(matches), case["matches"], "{case}");
        let prepared: Vec<_> = templates
            .matching_voices(trigger, key, velocity)
            .map(|name| name.as_str())
            .collect();
        assert_eq!(prepared, matches);
    }
    for overrides in data["invalid_template_overrides"].as_array().unwrap() {
        let mut voice = definitions[0].clone();
        voice.extend(overrides.as_object().unwrap().clone());
        let text = json!({"voices":[voice]}).to_string();
        assert!(
            codec::parse_synth_voice_templates(&text, Format::Json, limits).is_err(),
            "{overrides}"
        );
    }
}
