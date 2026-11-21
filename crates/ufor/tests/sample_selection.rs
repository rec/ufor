use serde_json::{Value, json};
use ufor::codec::{self, Format};
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
