use serde_json::{Value, json};
use ufor::codec::{self, Format};
use ufor::envelfo::PreparationLimits;
use ufor::error::Error;
use ufor::number::Rational;
use ufor::quantity;

#[test]
fn transport_and_elapsed_beats_match_the_shared_tempo_map() {
    let data: Value =
        serde_json::from_str(include_str!("../../../conformance/tempo-map.json")).unwrap();
    let limits = PreparationLimits::default();
    let clock = codec::parse_tempo_map(&data["map"].to_string(), Format::Json, limits).unwrap();
    let toml = codec::tempo_map_text(&clock, Format::Toml).unwrap();
    assert_eq!(
        codec::parse_tempo_map(&toml, Format::Toml, limits).unwrap(),
        clock
    );
    for (n, expected) in data["transport_beats"]
        .as_array()
        .unwrap()
        .iter()
        .enumerate()
    {
        assert_eq!(
            clock.beat_at(Rational::new(n as i64, 2).unwrap()).unwrap(),
            ratio(expected)
        );
    }
    for (n, expected) in data["elapsed_beats"].as_array().unwrap().iter().enumerate() {
        assert_eq!(
            clock.elapsed_beats(0.into(), (n as i64).into()).unwrap(),
            ratio(expected)
        );
    }
    for (n, expected) in data["elapsed_beat_times"]
        .as_array()
        .unwrap()
        .iter()
        .enumerate()
    {
        assert_eq!(
            clock.time_for_elapsed_beat((n as i64).into()).unwrap(),
            Some(ratio(expected))
        );
    }
    for row in data["quantized_beats"].as_array().unwrap() {
        assert_eq!(
            clock
                .quantized_beat(ratio(&row[0]), ratio(&row[1]))
                .unwrap(),
            ratio(&row[2])
        );
    }
    for row in data["pending_beats"].as_array().unwrap() {
        let expected = if row[2] == "seek" {
            Err(Error::TransportSeek)
        } else {
            Ok(Some(ratio(&row[2])))
        };
        assert_eq!(
            clock.time_for_beat(ratio(&row[0]), ratio(&row[1])),
            expected
        );
    }
    let points: Vec<_> = clock
        .frame_points(data["sample_rate"].as_i64().unwrap())
        .unwrap()
        .iter()
        .map(|point| {
            [
                point.frame,
                point.elapsed_beat,
                point.transport_beat,
                point.beats_per_frame,
            ]
            .map(|value| value.to_string())
        })
        .collect();
    assert_eq!(json!(points), data["frame_points"]);
}

#[test]
fn tempo_preparation_checks_bounds_and_preserves_fractional_frames() {
    let limits = PreparationLimits::default();
    for map in [
        r#"{"points":[]}"#,
        r#"{"points":[{"at_seconds":1,"beat":0,"bpm":120}]}"#,
        r#"{"points":[{"at_seconds":0,"beat":0,"bpm":0}]}"#,
        r#"{"points":[{"at_seconds":0.0,"beat":0,"bpm":120}]}"#,
    ] {
        assert!(codec::parse_tempo_map(map, Format::Json, limits).is_err());
    }
    let text = r#"{"points":[{"at_seconds":0,"beat":-2,"bpm":60},
        {"at_seconds":"1/100000","beat":8,"bpm":60,"running":false}]}"#;
    let clock = codec::parse_tempo_map(text, Format::Json, limits).unwrap();
    assert!(
        codec::parse_tempo_map(text, Format::Json, PreparationLimits::new(1).unwrap()).is_err()
    );
    let points = clock.frame_points(48000).unwrap();
    assert_eq!(points[1].frame, Rational::new(12, 25).unwrap());
    assert_eq!(points[1].elapsed_beat, Rational::new(1, 100000).unwrap());
    assert_eq!(clock.time_for_elapsed_beat(1.into()).unwrap(), None);
    assert_eq!(clock.time_for_beat(9.into(), 1.into()).unwrap(), None);
    assert!(clock.frame_points(0).is_err());
    assert_eq!(
        Rational::from(i64::MAX).checked_add(1.into()),
        Err(Error::ArithmeticRange)
    );
    assert_eq!(Rational::new(-3, 2).unwrap().ceil(), -1);
}

fn ratio(value: &Value) -> Rational {
    quantity::exact(value.as_str().unwrap(), "ratio").unwrap()
}
