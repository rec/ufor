use serde_json::{Value, json};
use ufor::codec::{Format, parse_midi_bindings, parse_score, score_text};
use ufor::envelfo::PreparationLimits;
use ufor::identifier::Identifier;
use ufor::performance_binding::{HeldNotes, RepeatedKeyRelease};
use ufor::score::Score;

const BINDINGS: &str = r#"{"kind":"performance_binding","name":"midi","title":"MIDI",
  "body":{"instrument":{"path":"instrument.toml"},"midi":[
    {"channels":[16,1],"part":"lead","repeated_key_release":"newest",
     "controllers":[{"number":11,"control":"volume","minimum":-0.5,"maximum":0.25}],
     "pitch_bend":{"control":"bend","minimum":-0.75,"center":0.25,"maximum":1}},
    {"channels":[3],"part":"bass","repeated_key_release":"oldest"},
    {"channels":[4],"part":"lead","repeated_key_release":"oldest"}
]}}"#;

#[test]
fn shared_performance_binding_score_round_trips() {
    let text = include_str!("../../../conformance/performance-binding.json");
    let limits = PreparationLimits::default();
    let score = parse_score(text, Format::Json, limits).unwrap();
    let Score::PerformanceBinding(binding) = &score else {
        panic!("expected performance binding");
    };
    assert_eq!(binding.instrument().key(), "instrument.toml");
    assert_eq!(binding.tuning_references().count(), 0);
    for format in [Format::Json, Format::Toml] {
        let text = score_text(&score, format).unwrap();
        assert_eq!(parse_score(&text, format, limits).unwrap(), score);
    }
}

#[test]
fn midi_bindings_preserve_part_order_and_pairing_by_channel() {
    let text = toml::to_string(&serde_json::from_str::<Value>(BINDINGS).unwrap()).unwrap();
    let bindings =
        parse_midi_bindings(&text, "", Format::Toml, PreparationLimits::default()).unwrap();
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
        parse_midi_bindings(BINDINGS, "{}", Format::Json, PreparationLimits::default()).unwrap();
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
fn midi_preparation_checks_instrument_domains_and_resolves_channel_tunings() {
    let mut document: Value = serde_json::from_str(BINDINGS).unwrap();
    let mut context = json!({"controls": {"volume": {"polarity": "bipolar"}, "bend": {}}});
    document["body"]["midi"][0]["tuning"] = json!({"selector":" concert#live#live "});
    document["body"]["midi"][2]["tuning"] = json!({"selector":"concert#live"});
    let prepare = |context: &Value| {
        parse_midi_bindings(
            &document.to_string(),
            &context.to_string(),
            Format::Json,
            PreparationLimits::default(),
        )
    };
    assert!(
        matches!(prepare(&context), Err(error) if error.to_string().contains("MIDI control bend"))
    );
    context["controls"]["bend"]["polarity"] = json!("bipolar");
    assert!(
        matches!(prepare(&context), Err(error) if error.to_string().contains("Unresolved tuning: selector:concert#live"))
    );
    context["tunings"] = json!({"selector:concert#live": {"source": {}, "root_frequency": "432"}});
    let bindings = prepare(&context).unwrap();
    for (records, accepted) in [(16, false), (17, true)] {
        assert_eq!(
            parse_midi_bindings(
                &document.to_string(),
                &context.to_string(),
                Format::Json,
                PreparationLimits::new(records).unwrap(),
            )
            .is_ok(),
            accepted,
        );
    }
    for channel in [1, 4, 16] {
        assert_eq!(
            bindings
                .tuning(channel)
                .unwrap()
                .evaluate(69)
                .unwrap()
                .as_f64(),
            432.0
        );
    }
    assert!(bindings.tuning(3).is_none());
}

#[test]
fn portable_bindings_reject_ambiguous_routes_and_invalid_ranges() {
    let original: Value = serde_json::from_str(BINDINGS).unwrap();
    for (path, value) in [
        ("/body/midi/1/channels/0", json!(1)),
        ("/body/midi/0/controllers/0/number", json!(128)),
        ("/body/midi/0/controllers/0/maximum", json!(-0.75)),
        ("/body/midi/0/pitch_bend/center", json!(-1)),
        ("/body/instrument", json!({"path":"/absolute.toml"})),
    ] {
        let mut document = original.clone();
        *document.pointer_mut(path).unwrap() = value;
        assert!(
            parse_score(
                &document.to_string(),
                Format::Json,
                PreparationLimits::default()
            )
            .is_err()
        );
    }
}

#[test]
fn held_notes_preserve_channel_pairing_and_ids_across_restart() {
    let mut notes = HeldNotes::new(Identifier::new("keys".into()).unwrap(), 3).unwrap();
    let first = notes.note_on(1, 69, 127, None).unwrap();
    let second = notes.note_on(1, 69, 64, None).unwrap();
    let other = notes.note_on(2, 69, 127, None).unwrap();
    assert_eq!((first.velocity, first.pitch_hz), (1.0, 440.0));
    assert_eq!(
        notes.note_off(1, 69, RepeatedKeyRelease::Newest).unwrap(),
        second.trigger_id
    );
    assert_eq!(
        notes.note_off(2, 69, RepeatedKeyRelease::Oldest).unwrap(),
        other.trigger_id
    );
    assert_eq!(
        notes.note_off(1, 69, RepeatedKeyRelease::Oldest).unwrap(),
        first.trigger_id
    );
    assert!(notes.note_off(1, 69, RepeatedKeyRelease::Oldest).is_err());
    assert!(notes.stopped());
    notes.restart();
    assert_eq!(
        notes.note_on(1, 69, 127, None).unwrap().trigger_id,
        "keys-note-3"
    );
    assert!(notes.finish().is_err());
    assert!(notes.stopped());
}
