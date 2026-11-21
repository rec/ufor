use serde_json::{Value, json};
use ufor::codec::{self, Format};
use ufor::control::schedule::{EventCoordinate, schedule_commands};
use ufor::envelfo::PreparationLimits;
use ufor::error::Error;
use ufor::number::Rational;

#[test]
fn command_coordinates_match_shared_cases() {
    let vectors: Value =
        serde_json::from_str(include_str!("../../../conformance/command-schedule.json")).unwrap();
    for spec in vectors["cases"].as_array().unwrap() {
        let tempo = codec::parse_tempo_map(
            &spec["tempo"].to_string(),
            Format::Json,
            PreparationLimits::default(),
        )
        .unwrap();
        let mut events: Vec<_> = spec["events"]
            .as_array()
            .unwrap()
            .iter()
            .map(|event| EventCoordinate {
                tick: event[0].as_i64().unwrap(),
                ordinal: event[1].as_u64().unwrap(),
                quantize_beats: event[2].as_array().map(|division| {
                    Rational::new(division[0].as_i64().unwrap(), division[1].as_i64().unwrap())
                        .unwrap()
                }),
            })
            .collect();
        let sample_rate = spec["sample_rate"].as_i64().unwrap();
        let coordinates: Vec<_> = schedule_commands(&tempo, sample_rate, &events)
            .unwrap()
            .into_iter()
            .map(|event| json!([event.index, event.tick, event.ordinal]))
            .collect();
        assert_eq!(json!(coordinates), spec["scheduled"], "{}", spec["name"]);
        if spec["name"] == "fractional frame rounds up once" {
            events[1].ordinal = u64::MAX;
            assert_eq!(
                schedule_commands(&tempo, sample_rate, &events),
                Err(Error::ArithmeticRange)
            );
        }
    }
}
