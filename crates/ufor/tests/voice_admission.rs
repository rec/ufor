use serde_json::{Value, json};
use ufor::codec::{self, Format};

#[test]
fn admission_applies_chokes_pools_and_global_limit_in_order() {
    let data: Value =
        serde_json::from_str(include_str!("../../../conformance/voice-admission.json")).unwrap();
    let mut batch = data["batch"].clone();
    let actions = codec::parse_voice_admission(&batch.to_string(), Format::Json)
        .unwrap()
        .retirements()
        .unwrap();
    for action in &actions {
        assert_eq!(action.tick, batch["tick"].as_i64().unwrap());
        assert_eq!(action.ordinal, batch["ordinal"].as_u64().unwrap());
    }
    let observed: Vec<_> = actions
        .iter()
        .map(|r| json!([r.voice_id, r.cause, r.action, r.fade_seconds]))
        .collect();
    assert_eq!(json!(observed), data["retirements"]);

    batch["pool_counts"]["a"] = json!(2);
    let error = codec::parse_voice_admission(&batch.to_string(), Format::Json)
        .unwrap()
        .retirements()
        .unwrap_err();
    assert!(
        error
            .to_string()
            .contains("trigger batch exceeds voice pool a limit")
    );
}
