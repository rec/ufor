use serde_json::Value;
use ufor::codec::{self, Format};

#[test]
fn slot_eligibility_matches_shared_cases() {
    let data: Value =
        serde_json::from_str(include_str!("../../../conformance/sample-eligibility.json")).unwrap();
    let slots = data["slots"].to_string();
    let eligibility = codec::parse_sample_eligibility(&slots, Format::Json, 4).unwrap();
    assert!(codec::parse_sample_eligibility(&slots, Format::Json, 3).is_err());
    for case in data["cases"].as_array().unwrap() {
        let mut context = data["context"].as_object().unwrap().clone();
        context.extend(case["changes"].as_object().unwrap().clone());
        let context = codec::parse_sample_eligibility_context(
            &Value::Object(context).to_string(),
            Format::Json,
        )
        .unwrap();
        let matches: Vec<_> = eligibility
            .matching_slots(&context)
            .unwrap()
            .into_iter()
            .map(|name| name.as_str())
            .collect();
        assert_eq!(serde_json::json!(matches), case["matches"], "{case}");
    }
}
