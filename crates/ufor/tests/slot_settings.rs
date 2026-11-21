use serde_json::Value;
use ufor::codec::{self, Format};
use ufor::envelfo::PreparationLimits;
use ufor::modulation::Target;
use ufor::samples::inheritance::resolve_slot_settings;
use ufor::samples::processing::{SoundSettings, TargetResolution};

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
        let resolved = resolve_slot_settings(&case["slot"].to_string(), group).unwrap();
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
