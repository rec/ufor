use serde_json::{Value, json};
use ufor::codec::{self, Format};
use ufor::envelfo::PreparationLimits;
use ufor::identifier::Identifier;
use ufor::samples::selection::{Mode, Sequence};

#[test]
fn choices_and_restored_state_match_shared_vectors() {
    let data: Value =
        serde_json::from_str(include_str!("../../../conformance/selection.json")).unwrap();
    let seed = data["seed"].as_u64().unwrap();
    let input = json!({
        "part": data["part"],
        "selection": data["selection"],
        "trigger": data["trigger"],
        "key": data["key"],
        "candidates": data["candidates"],
    })
    .to_string();
    for (name, mode) in [
        ("cycle", Mode::Cycle),
        ("random", Mode::Random),
        ("shuffle", Mode::Shuffle),
    ] {
        let mut sequence = codec::parse_sample_selection_sequence(&input, Format::Json).unwrap();
        for (index, expected) in data["choices"][name].as_array().unwrap().iter().enumerate() {
            let (choice, next) = sequence.advance(mode, seed).unwrap();
            assert_eq!(
                choice.as_str(),
                expected.as_str().unwrap(),
                "{name}[{index}]"
            );
            sequence = next;
            if index == 0 {
                assert_eq!(state(&sequence), data["after_first"][name]);
                let saved = serde_json::to_string(&sequence).unwrap();
                sequence = codec::parse_sample_selection_sequence(&saved, Format::Json).unwrap();
            }
        }
        assert_eq!(state(&sequence), data["final"][name]);
        sequence.counter = u64::MAX;
        assert!(sequence.advance(mode, seed).is_err());
    }
}

fn state(sequence: &Sequence) -> Value {
    json!({
        "counter": sequence.counter,
        "remaining": sequence.remaining,
        "previous": sequence.previous,
    })
}

#[test]
fn take_selector_preserves_linked_order_and_independent_partitions() {
    let data: Value =
        serde_json::from_str(include_str!("../../../conformance/selection.json")).unwrap();
    let cases = &data["take_selector"];
    let definition = toml::to_string(&cases["definition"]).unwrap();
    let mut selector = codec::parse_sample_take_selector(
        &definition,
        Format::Toml,
        42,
        PreparationLimits::default(),
    )
    .unwrap();
    for step in cases["steps"].as_array().unwrap() {
        let eligible: Vec<Identifier> = serde_json::from_value(step["eligible"].clone()).unwrap();
        let selected = selector
            .select(
                &eligible,
                &serde_json::from_value(step["part"].clone()).unwrap(),
                serde_json::from_value(step["trigger"].clone()).unwrap(),
                step["key"].as_i64(),
            )
            .unwrap();
        assert_eq!(json!(selected), step["selected"]);
    }
    let before = json!(selector.sequences().collect::<Vec<_>>());
    assert_eq!(before, cases["final"]);
    let grouped = Identifier::new("second".into()).unwrap();
    assert!(
        selector
            .select(
                &[grouped],
                &Identifier::new("left".into()).unwrap(),
                ufor::samples::eligibility::Trigger::Control,
                None
            )
            .is_err()
    );
    assert_eq!(json!(selector.sequences().collect::<Vec<_>>()), before);
}
