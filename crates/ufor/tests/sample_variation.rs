use serde_json::{Value, json};
use ufor::codec::{self, Format};
use ufor::identifier::Identifier;
use ufor::samples::variation::{DrawEvent, Variation};

#[test]
fn sampler_draws_match_shared_vectors() {
    let ranges: Value =
        serde_json::from_str(include_str!("../../../conformance/random-ranges.json")).unwrap();
    for case in ranges["cases"].as_array().unwrap() {
        let event = event(&ranges, case);
        assert_eq!(
            event.random_range_value(),
            case["expected"].as_f64().unwrap()
        );
    }

    let variations: Value =
        serde_json::from_str(include_str!("../../../conformance/variation.json")).unwrap();
    let variation =
        codec::parse_sample_variation(&variations["variation"].to_string(), Format::Json).unwrap();
    for case in variations["cases"].as_array().unwrap() {
        let event = event(&variations, case);
        let identity: Identifier = serde_json::from_value(case["identity"].clone()).unwrap();
        let resolved = variation.resolve(&event, &identity).unwrap();
        assert_eq!(serde_json::to_value(resolved).unwrap(), case["expected"]);

        let largest_offset = Variation {
            offset_frames: i64::MAX,
            ..Variation::default()
        };
        assert!(
            largest_offset
                .resolve(&event, &identity)
                .unwrap()
                .offset_frames
                >= 0
        );
    }
}

fn event(data: &Value, case: &Value) -> DrawEvent {
    serde_json::from_value(json!({
        "seed": data["seed"],
        "part": case["part"],
        "trigger_id": case["trigger_id"],
        "tick": case["tick"],
        "ordinal": case["ordinal"],
    }))
    .unwrap()
}
