use serde_json::Value;
use ufor::codec::{Format, parse_performance_event, performance_event_text};
use ufor::events::Action;
use ufor::number::Rational;

#[test]
fn shared_performance_events_validate_and_round_trip() {
    let vectors: Value =
        serde_json::from_str(include_str!("../../../conformance/performance-events.json")).unwrap();
    for spec in vectors["valid"].as_array().unwrap() {
        let event = parse_performance_event(&spec.to_string(), Format::Json)
            .unwrap_or_else(|error| panic!("{spec}: {error}"));
        assert_eq!(event.tick, spec["tick"].as_i64().unwrap());
        assert_eq!(event.ordinal, spec["ordinal"].as_u64().unwrap());
        match event.payload.action() {
            Action::Trigger {
                pitch_hz, velocity, ..
            } => {
                assert_eq!((*pitch_hz, *velocity), (Some(432.0), 1.0));
            }
            Action::EnvelfoChange {
                quantize_beats: Some(division),
                ..
            } => {
                assert_eq!(*division, Rational::new(1, 4).unwrap());
            }
            _ => {}
        }
        for format in [Format::Json, Format::Toml] {
            let text = performance_event_text(&event, format).unwrap();
            assert_eq!(parse_performance_event(&text, format).unwrap(), event);
        }
    }
    for spec in vectors["invalid"].as_array().unwrap() {
        assert!(
            parse_performance_event(&spec.to_string(), Format::Json).is_err(),
            "{spec}"
        );
    }
}
