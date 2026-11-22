use serde_json::{Value, json};
use ufor::codec::{Format, parse_performance_event, performance_event_text};
use ufor::events::{Action, PerformanceEvent, prepare_performance};
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

#[test]
fn ordinary_performance_checks_coordinates_and_control_domains_without_a_clock() {
    let vectors: Value =
        serde_json::from_str(include_str!("../../../conformance/performance-events.json")).unwrap();
    let valid = vectors["valid"].as_array().unwrap();
    let mut events: Vec<PerformanceEvent> = [2, 1, 0, 3]
        .into_iter()
        .map(|index| serde_json::from_value(valid[index].clone()).unwrap())
        .collect();
    let controls =
        serde_json::from_value(json!({"bend":{"polarity":"bipolar"}, "volume":{}})).unwrap();
    let ordered = prepare_performance(&events, &controls, None).unwrap();
    assert_eq!(
        ordered.iter().map(|event| event.index).collect::<Vec<_>>(),
        [2, 1, 0, 3]
    );
    let incomplete = serde_json::from_value(json!({"bend":{"polarity":"bipolar"}})).unwrap();
    let error = prepare_performance(&events, &incomplete, None).unwrap_err();
    assert!(error.to_string().contains("Unknown control: volume"));
    let unipolar = serde_json::from_value(json!({"bend":{}, "volume":{}})).unwrap();
    let error = prepare_performance(&events, &unipolar, None).unwrap_err();
    assert!(error.to_string().contains("Control bend"));
    events.push(events[0].clone());
    let error = prepare_performance(&events, &controls, None).unwrap_err();
    assert!(error.to_string().contains("duplicate event coordinate"));
}
