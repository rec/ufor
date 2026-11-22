use serde_json::{Value, json};
use ufor::codec::{Format, parse_midi_bindings};
use ufor::envelfo::PreparationLimits;
use ufor::performance_binding::RepeatedKeyRelease;

const BINDINGS: &str = r#"{"midi":[
    {"channels":[16,1],"part":"lead","repeated_key_release":"newest",
     "controllers":[{"number":11,"control":"volume","minimum":-0.5,"maximum":0.25}],
     "pitch_bend":{"control":"bend","minimum":-0.75,"center":0.25,"maximum":1}},
    {"channels":[3],"part":"bass","repeated_key_release":"oldest"},
    {"channels":[4],"part":"lead","repeated_key_release":"oldest"}
]}"#;

#[test]
fn midi_bindings_preserve_part_order_and_pairing_by_channel() {
    let text = toml::to_string(&serde_json::from_str::<Value>(BINDINGS).unwrap()).unwrap();
    let bindings = parse_midi_bindings(&text, Format::Toml, PreparationLimits::default()).unwrap();
    assert_eq!(
        bindings
            .parts()
            .map(|part| part.as_str())
            .collect::<Vec<_>>(),
        ["lead", "bass"]
    );
    let (part, policy) = bindings.note_route(16).unwrap();
    assert_eq!(
        (part.as_str(), policy),
        ("lead", RepeatedKeyRelease::Newest)
    );
    let (part, policy) = bindings.note_route(4).unwrap();
    assert_eq!(
        (part.as_str(), policy),
        ("lead", RepeatedKeyRelease::Oldest)
    );
    assert!(bindings.note_route(2).is_none());
}

#[test]
fn midi_control_mapping_preserves_endpoints_and_absent_routes() {
    let bindings =
        parse_midi_bindings(BINDINGS, Format::Json, PreparationLimits::default()).unwrap();
    let control = bindings.control_change(1, 11, 127).unwrap().unwrap();
    assert_eq!(
        (
            control.part.as_str(),
            control.control.as_str(),
            control.value
        ),
        ("lead", "volume", 0.25)
    );
    assert_eq!(
        bindings.control_change(1, 11, 0).unwrap().unwrap().value,
        -0.5
    );
    for (input, expected) in [(-8192, -0.75), (-4096, -0.25), (0, 0.25), (8191, 1.0)] {
        assert_eq!(
            bindings.pitch_bend(16, input).unwrap().unwrap().value,
            expected
        );
    }
    assert!(bindings.control_change(1, 10, 64).unwrap().is_none());
    assert!(bindings.pitch_bend(3, 0).unwrap().is_none());
    assert!(bindings.pitch_bend(1, 8192).is_err());
}

#[test]
fn portable_bindings_reject_ambiguous_routes_and_invalid_ranges() {
    let original: Value = serde_json::from_str(BINDINGS).unwrap();
    for (path, value) in [
        ("/midi/1/channels/0", json!(1)),
        ("/midi/0/controllers/0/number", json!(128)),
        ("/midi/0/controllers/0/maximum", json!(-0.75)),
        ("/midi/0/pitch_bend/center", json!(-1)),
    ] {
        let mut document = original.clone();
        *document.pointer_mut(path).unwrap() = value;
        assert!(
            parse_midi_bindings(
                &document.to_string(),
                Format::Json,
                PreparationLimits::default()
            )
            .is_err()
        );
    }
}
