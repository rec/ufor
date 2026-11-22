use serde_json::{Value, json};
use ufor::codec::{
    Format, parse_event_sequence, parse_sequence_selection, sequence_selection_text,
};
use ufor::envelfo::PreparationLimits;
use ufor::playback::{plan_playback, state_at};

const CASES: &str = include_str!("../../../conformance/sequence-playback.json");

#[test]
fn shared_loop_matches_exact_destinations_and_scoped_ids() {
    let vectors: Value = serde_json::from_str(CASES).unwrap();
    let source = parse_event_sequence(
        &vectors["sequence"].to_string(),
        Format::Json,
        PreparationLimits::default(),
    )
    .unwrap();
    let selection =
        parse_sequence_selection(&vectors["selection"].to_string(), Format::Json).unwrap();
    let text = sequence_selection_text(&selection, Format::Toml).unwrap();
    assert_eq!(
        parse_sequence_selection(&text, Format::Toml).unwrap(),
        selection
    );
    let loops = plan_playback(&source, selection)
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    let actual: Vec<_> = loops
        .iter()
        .map(|plan| {
            let value = serde_json::to_value(plan).unwrap();
            json!({
                "start": plan.start,
                "end": plan.end,
                "trigger_id": value["events"][0]["trigger_id"],
                "trigger_tick": plan.events[0].tick,
                "release_tick": plan.cleanup[0].tick,
            })
        })
        .collect();
    assert_eq!(json!(actual), vectors["expected"]);
}

#[test]
fn mixed_selection_preserves_capture_and_control_order_and_closes_each_part() {
    let vectors: Value = serde_json::from_str(CASES).unwrap();
    let spec = &vectors["mixed"];
    let source = parse_event_sequence(
        &spec["sequence"].to_string(),
        Format::Json,
        PreparationLimits::default(),
    )
    .unwrap();
    let state = serde_json::to_value(state_at(&source, 1).unwrap()).unwrap();
    assert_eq!(state["triggers"][0]["velocity"], 0.0);
    assert_eq!(
        json!(project(&state["controls"], &["tick", "control"])),
        json!([[0, "gain"], [-2, "bend"], [-1, "expression"]])
    );
    assert_eq!(state_at(&source, 4).unwrap().controls.len(), 2);
    assert!(state_at(&source, 8).is_err());
    for mode in ["retrigger_active", "omit_active"] {
        let mut selection = spec["selection"].clone();
        selection["active_notes"] = json!(mode);
        let selection = parse_sequence_selection(&selection.to_string(), Format::Json).unwrap();
        let plan = plan_playback(&source, selection)
            .unwrap()
            .next()
            .unwrap()
            .unwrap();
        assert_eq!((plan.start, plan.end), (-10, -7));
        assert!(plan.cleanup.iter().all(|event| event.tick == -7));
        let value = serde_json::to_value(plan).unwrap();
        let actual = json!({
            "controls": project(&value["controls"], &["ordinal", "control", "value"]),
            "events": project(&value["events"], &["kind", "tick", "ordinal", "part", "trigger_id"]),
            "captured": project(&value["captured"], &["kind", "tick", "ordinal"]),
            "cleanup": project(&value["cleanup"], &["part", "trigger_id", "ordinal"]),
        });
        assert_eq!(actual, spec[mode]);
        assert_eq!(value["captured"][0]["data"], json!([144, 60, 127]));
        assert_eq!(value["captured"][1]["trigger_id"], "note");
    }
}

#[test]
fn selection_is_lazy_and_rejects_coordinate_overflow() {
    let source = parse_event_sequence(
        r#"{"timebase":"clock","end":1}"#,
        Format::Json,
        PreparationLimits::default(),
    )
    .unwrap();
    let mut definition = json!({
        "name":"silent","interval":{"start":0,"end":1},"repetitions": 1_000_000_000
    });
    let selection = parse_sequence_selection(&definition.to_string(), Format::Json).unwrap();
    let mut plan = plan_playback(&source, selection).unwrap();
    assert_eq!(plan.next().unwrap().unwrap().iteration, 0);
    assert_eq!(plan.next().unwrap().unwrap().iteration, 1);
    definition["start"] = json!(i64::MAX - 1);
    let selection = parse_sequence_selection(&definition.to_string(), Format::Json).unwrap();
    assert!(plan_playback(&source, selection).is_err());
    definition["repetitions"] = json!(0);
    assert!(parse_sequence_selection(&definition.to_string(), Format::Json).is_err());
}

#[test]
fn invalid_ownership_fails_before_any_repetition_is_returned() {
    let vectors: Value = serde_json::from_str(CASES).unwrap();
    let spec = &vectors["mixed"];
    let mut sequence = spec["sequence"].clone();
    sequence["events"][5]["trigger_id"] = json!("missing");
    let source = parse_event_sequence(
        &sequence.to_string(),
        Format::Json,
        PreparationLimits::default(),
    )
    .unwrap();
    assert!(state_at(&source, 1).is_ok());
    assert!(state_at(&source, 2).is_err());
    let selection = parse_sequence_selection(&spec["selection"].to_string(), Format::Json).unwrap();
    assert!(plan_playback(&source, selection).is_err());
}

fn project(events: &Value, fields: &[&str]) -> Vec<Vec<Value>> {
    events
        .as_array()
        .unwrap()
        .iter()
        .map(|event| fields.iter().map(|key| event[*key].clone()).collect())
        .collect()
}
