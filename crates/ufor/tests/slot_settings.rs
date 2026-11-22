use serde_json::Value;
use ufor::codec::{self, Format};
use ufor::envelfo::PreparationLimits;
use ufor::modulation::Target;
use ufor::samples::inheritance::resolve_slot_settings;
use ufor::samples::processing::{SoundSettings, TargetResolution};
use ufor::samples::slots::PreparedSlots;

#[test]
fn slot_categories_and_selection_match_shared_vectors() {
    // Keep the authored group JSON so the intentionally unsorted keys survive.
    let vectors: std::collections::BTreeMap<String, Box<serde_json::value::RawValue>> =
        serde_json::from_str(include_str!("../../../conformance/slot-settings.json")).unwrap();
    let cases: Vec<Value> = serde_json::from_str(vectors["cases"].get()).unwrap();
    for case in cases {
        let group = case["grouped"]
            .as_bool()
            .unwrap()
            .then(|| vectors["group"].get());
        let projected = resolve_slot_settings(&case["slot"].to_string(), group).unwrap();
        let mut slot = case["slot"].clone();
        slot["name"] = serde_json::json!("voice");
        slot["slice"] = serde_json::json!("audio");
        slot["mapping"] =
            serde_json::json!({"lowest_key":60,"highest_key":72,"reference_pitch_hz":440});
        slot["channels"] = serde_json::json!([{"input":"mono","output":"left"}]);
        let groups = if let Some(group) = group {
            slot["group"] = serde_json::json!("kit");
            let group = group.trim().strip_prefix('{').unwrap();
            format!(r#"[{{"name":"kit",{group}]"#)
        } else {
            "[]".into()
        };
        let body = format!(r#"{{"kind":"sample_instrument","slots":[{slot}],"groups":{groups}}}"#);
        let prepared = PreparedSlots::from_json(&body, PreparationLimits::new(1).unwrap()).unwrap();
        let resolved = prepared.settings().values().next().unwrap();
        assert_eq!(
            serde_json::to_string(resolved).unwrap(),
            serde_json::to_string(&projected).unwrap()
        );
        let context = codec::parse_sample_eligibility_context(
            r#"{"trigger":"start","key":69,"velocity":1.0,"held_keys":[],"controls":{},"note_on_count":1,"random_value":0.0}"#,
            Format::Json,
        ).unwrap();
        assert_eq!(
            prepared.eligibility().matching_slots(&context).unwrap()[0].as_str(),
            "voice"
        );
        assert_eq!(
            resolved.selection.as_ref().map(|name| name.as_str()),
            case["selection"].as_str()
        );
        let text = serde_json::to_string(&resolved.settings).unwrap();
        let settings =
            codec::parse_sound_settings(&text, Format::Json, PreparationLimits::default()).unwrap();
        assert_eq!(
            target(&settings, "volume_db"),
            case["volume_db"].as_f64().unwrap()
        );
        assert_eq!(
            target(&settings, "tuning_cents"),
            case["tuning_cents"].as_f64().unwrap()
        );
        assert_eq!(
            settings.envelope().is_some(),
            case["envelope"].as_bool().unwrap()
        );
        let names: Vec<_> = settings
            .envelfos()
            .iter()
            .map(|(name, _)| name.as_str())
            .collect();
        assert_eq!(serde_json::json!(names), case["envelfos"]);
    }
}

fn target(settings: &SoundSettings, field: &str) -> f64 {
    let target: Target =
        serde_json::from_value(serde_json::json!({"name":"processing", "parameter":field}))
            .unwrap();
    let TargetResolution::Resolved(resolved) = settings.resolve_target(&target).unwrap() else {
        panic!("processing target")
    };
    resolved.default_value
}
