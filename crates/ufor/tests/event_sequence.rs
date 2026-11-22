use serde_json::{Value, json};
use ufor::codec::{
    Format, event_sequence_text, parse_event_sequence, parse_score, parse_stored_event, score_text,
    stored_event_text,
};
use ufor::envelfo::PreparationLimits;
use ufor::events::EventKind;
use ufor::score::Score;

const CASES: &str = include_str!("../../../conformance/event-sequence.json");

#[test]
fn mixed_sequence_round_trips_without_losing_captured_arguments() {
    let vectors: Value = serde_json::from_str(CASES).unwrap();
    let limits = PreparationLimits::default();
    let mut definition = vectors["score"].clone();
    let score = parse_score(&definition.to_string(), Format::Json, limits).unwrap();
    let Score::Sequence(sequence) = &score else {
        panic!("expected sequence score");
    };
    assert_eq!(sequence.tags(), ["#test", "#sequence"]);
    assert_eq!(sequence.body().start(), -4);
    assert_eq!(sequence.body().end(), 10);
    assert_eq!(
        sequence
            .body()
            .events()
            .iter()
            .map(|event| event.payload.kind())
            .collect::<Vec<_>>(),
        [
            EventKind::Midi,
            EventKind::Ump,
            EventKind::Key,
            EventKind::Osc,
            EventKind::Trigger,
            EventKind::Release
        ]
    );
    let osc = &sequence.body().events()[3];
    let text = stored_event_text(osc, Format::Json).unwrap();
    let exported: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(
        exported["decoded"][0]["args"],
        json!(["text", 7, 0.5, true, null])
    );
    assert_eq!(parse_stored_event(&text, Format::Json).unwrap(), *osc);
    assert!(stored_event_text(osc, Format::Toml).is_err());
    assert!(score_text(&score, Format::Toml).is_err());
    assert!(event_sequence_text(sequence.body(), Format::Toml).is_err());
    let text = score_text(&score, Format::Json).unwrap();
    assert_eq!(parse_score(&text, Format::Json, limits).unwrap(), score);

    definition["body"]["events"][3]["decoded"][0]["args"]
        .as_array_mut()
        .unwrap()
        .pop();
    let score = parse_score(&definition.to_string(), Format::Json, limits).unwrap();
    let text = score_text(&score, Format::Toml).unwrap();
    assert_eq!(parse_score(&text, Format::Toml, limits).unwrap(), score);
}

#[test]
fn sequence_rejects_invalid_packets_order_and_output_contracts() {
    let vectors: Value = serde_json::from_str(CASES).unwrap();
    let limits = PreparationLimits::default();
    for event in vectors["invalid_events"].as_array().unwrap() {
        assert!(
            parse_stored_event(&event.to_string(), Format::Json).is_err(),
            "{event}"
        );
    }
    for sequence in vectors["invalid_sequences"].as_array().unwrap() {
        assert!(
            parse_event_sequence(&sequence.to_string(), Format::Json, limits).is_err(),
            "{sequence}"
        );
    }
    for (field, invalid) in [
        ("/timebases/0/name", json!("other")),
        (
            "/outputs/0/stream/kinds",
            json!(["midi", "ump", "key", "osc", "trigger"]),
        ),
        ("/outputs/0/binding/sequence", json!(false)),
        ("/outputs/0/stream/timebase", json!("other")),
    ] {
        let mut score = vectors["score"].clone();
        *score.pointer_mut(field).unwrap() = invalid;
        assert!(
            parse_score(&score.to_string(), Format::Json, limits).is_err(),
            "{field}"
        );
    }
    let small = PreparationLimits::new(6).unwrap();
    assert!(
        parse_event_sequence(&vectors["score"]["body"].to_string(), Format::Json, small).is_err()
    );
}

#[test]
fn osc_capture_rejects_unsigned_arguments_outside_the_exact_integer_domain() {
    let vectors: Value = serde_json::from_str(CASES).unwrap();
    let mut packet = vectors["score"]["body"]["events"][3].clone();
    packet["decoded"][0]["args"][1] = json!(i64::MAX);
    let stored = parse_stored_event(&packet.to_string(), Format::Json).unwrap();
    let text = stored_event_text(&stored, Format::Json).unwrap();
    let round_trip: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(round_trip["decoded"][0]["args"][1], json!(i64::MAX));

    packet["decoded"][0]["args"][1] = json!(i64::MAX as u64 + 1);
    assert!(parse_stored_event(&packet.to_string(), Format::Json).is_err());
    let text = packet
        .to_string()
        .replace("9223372036854775808", "18446744073709551616");
    assert!(parse_stored_event(&text, Format::Json).is_err());
    let text = vectors["score"]
        .to_string()
        .replace(",7,0.5", ",-9223372036854775809,0.5");
    assert!(parse_score(&text, Format::Json, PreparationLimits::default()).is_err());
}
