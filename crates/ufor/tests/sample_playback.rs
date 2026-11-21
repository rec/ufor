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
