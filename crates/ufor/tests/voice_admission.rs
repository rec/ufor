use serde_json::{Value, json};
use ufor::codec::{self, Format};

#[test]
fn shared_voice_declarations_validate_in_standalone_and_batch_inputs() {
    let data: Value =
        serde_json::from_str(include_str!("../../../conformance/voice-admission.json")).unwrap();
    for case in data["chokes"].as_array().unwrap() {
        let choke = codec::parse_choke(&case["input"].to_string(), Format::Json);
        if case["invalid"] == true {
            assert!(choke.is_err(), "{case}");
            let mut batch = data["batch"].clone();
            batch["chokes"] = json!([case["input"]]);
            assert!(codec::parse_voice_admission(&batch.to_string(), Format::Json).is_err());
        } else {
            let choke = choke.unwrap();
            assert_eq!(json!(choke.fade_seconds()), case["fade_seconds"]);
            let text = toml::to_string(&choke).unwrap();
            assert_eq!(codec::parse_choke(&text, Format::Toml).unwrap(), choke);
        }
    }
    for case in data["voice_policies"].as_array().unwrap() {
        let policy = codec::parse_voice_policy(&case["input"].to_string(), Format::Json);
        let pool = json!({"name":"lead","policy":case["input"]});
        let pool = codec::parse_voice_pool(&pool.to_string(), Format::Json);
        if case["invalid"] == true {
            assert!(policy.is_err() && pool.is_err(), "{case}");
        } else {
            let pool = pool.unwrap();
            assert_eq!(pool.policy, policy.unwrap());
            assert_eq!(json!(pool.policy), case["expected"]);
            let text = toml::to_string(&pool).unwrap();
            assert_eq!(codec::parse_voice_pool(&text, Format::Toml).unwrap(), pool);
        }
    }
}

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
