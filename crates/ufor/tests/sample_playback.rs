use serde_json::{Value, json};
use ufor::codec::{self, Format};
use ufor::samples::playback::{Direction, Playback, PlaybackMode};

#[test]
fn sample_traversal_matches_shared_authored_cases() {
    let data: Value =
        serde_json::from_str(include_str!("../../../conformance/sample-playback.json")).unwrap();
    let mut definition = data["slice"].clone();
    let slice = codec::parse_sample_slice(&definition.to_string(), Format::Json).unwrap();
    assert_eq!(json!(slice), definition);
    let toml = toml::to_string(&slice).unwrap();
    assert_eq!(
        codec::parse_sample_slice(&toml, Format::Toml).unwrap(),
        slice
    );
    let playback =
        codec::parse_sample_playback(&data["playback"].to_string(), Format::Json).unwrap();
    assert_eq!(json!(playback), data["playback"]);
    assert!(slice.validate_playback(playback, 20, 0).is_ok());
    assert!(slice.validate_playback(playback, 19, 0).is_err());
    assert!(slice.validate_playback(playback, 20, 1).is_err());
    assert!(
        slice
            .validate_playback(
                Playback {
                    direction: Direction::Mirror,
                    ..playback
                },
                20,
                0
            )
            .is_err()
    );
    assert!(
        slice
            .validate_playback(
                Playback {
                    mode: PlaybackMode::OneShot,
                    ..playback
                },
                20,
                0
            )
            .is_err()
    );
    let mut wide = definition.clone();
    wide["loop"]["repeat_count"] = data["largest_repeat_count"].clone();
    assert_eq!(
        codec::parse_sample_slice(&wide.to_string(), Format::Json)
            .unwrap()
            .loop_settings()
            .unwrap()
            .repeat_count(),
        Some(u64::MAX)
    );
    for invalid in data["rejected_loops"].as_array().unwrap() {
        definition["loop"] = invalid.clone();
        assert!(codec::parse_sample_slice(&definition.to_string(), Format::Json).is_err());
    }
}

#[test]
fn sample_pitch_mapping_matches_shared_frequency_cases() {
    let data: Value =
        serde_json::from_str(include_str!("../../../conformance/sample-playback.json")).unwrap();
    for row in data["pitch_ratios"].as_array().unwrap() {
        let name = row[0].as_str().unwrap();
        let mapping =
            codec::parse_sample_mapping(&data["mappings"][name].to_string(), Format::Json).unwrap();
        let text = toml::to_string(&mapping).unwrap();
        assert_eq!(
            codec::parse_sample_mapping(&text, Format::Toml).unwrap(),
            mapping
        );
        assert_eq!(
            mapping
                .pitch_ratio(
                    row[1].as_f64(),
                    row[2].as_f64().unwrap(),
                    row[3].as_f64().unwrap()
                )
                .unwrap(),
            row[4].as_f64().unwrap()
        );
    }
    let mapping =
        codec::parse_sample_mapping(&data["mappings"]["tracked"].to_string(), Format::Json)
            .unwrap();
    for pitch in [None, Some(0.0), Some(f64::INFINITY)] {
        assert!(mapping.pitch_ratio(pitch, 0.0, 0.0).is_err());
    }
    assert!(mapping.pitch_ratio(Some(440.0), f64::MAX, 0.0).is_err());
    for raw in [
        r#"{"lowest_key":2,"highest_key":1,"pitch_tracking":false}"#,
        r#"{"lowest_key":0,"highest_key":1,"minimum_velocity":0.8,"maximum_velocity":0.5,"pitch_tracking":false}"#,
        r#"{"lowest_key":0,"highest_key":1}"#,
    ] {
        assert!(codec::parse_sample_mapping(raw, Format::Json).is_err());
    }
}

#[test]
fn slot_playback_resolves_overrides_and_rounds_the_combined_delay_once() {
    let data: Value =
        serde_json::from_str(include_str!("../../../conformance/sample-playback.json")).unwrap();
    let document: std::collections::BTreeMap<&str, &serde_json::value::RawValue> =
        serde_json::from_str(include_str!("../../../conformance/sample-playback.json")).unwrap();
    let slot = codec::parse_slot_playback(document["slot_playback"].get(), Format::Json).unwrap();
    let defaults =
        codec::parse_sample_playback(&data["slot_defaults"].to_string(), Format::Json).unwrap();
    assert!(slot.resolve(Playback::default()).is_err());
    let resolved = slot.resolve(defaults).unwrap();
    assert_eq!(resolved.additional_plays, u64::MAX);
    assert_eq!(resolved.playback.direction, Direction::Mirror);
    assert_eq!(resolved.playback.mode, PlaybackMode::OneShot);
    assert_eq!(resolved.end_fade_seconds, 0.125);
    for row in data["slot_delays"].as_array().unwrap() {
        let variation = ufor::quantity::exact(row[0].as_str().unwrap(), "seconds").unwrap();
        assert_eq!(
            resolved
                .delay_frames(variation, row[1].as_i64().unwrap())
                .unwrap(),
            row[2].as_i64().unwrap()
        );
    }
    let toml = codec::parse_slot_playback("start_delay_seconds = '1/8 s'", Format::Toml).unwrap();
    assert_eq!(
        toml.resolve(defaults)
            .unwrap()
            .delay_frames(0.into(), 48000)
            .unwrap(),
        6000
    );
    for raw in [
        r#"{"play_count":0}"#,
        r#"{"play_count":1.0}"#,
        r#"{"play_count":18446744073709551617}"#,
        r#"{"start_delay_seconds":-1}"#,
    ] {
        assert!(codec::parse_slot_playback(raw, Format::Json).is_err());
    }
}
