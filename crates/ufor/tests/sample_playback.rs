use serde_json::{Value, json};
use std::collections::BTreeMap;
use ufor::codec::{self, Format};
use ufor::control::Polarity;
use ufor::identifier::Identifier;
use ufor::number::Rational;
use ufor::samples::controls::ControlDeclaration;
use ufor::samples::crossfade::ControlScope;
use ufor::samples::playback::{
    Direction, Playback, PlaybackMode, maximum_sample_step, maximum_tuning_cents, onset_gain,
    sample_step, tuned_pitch_ratio,
};

#[test]
fn sample_crossfades_preserve_clipping_and_exact_endpoints() {
    let data: Value =
        serde_json::from_str(include_str!("../../../conformance/sample-crossfade.json")).unwrap();
    let parse =
        |name| codec::parse_sample_crossfade(&data[name].to_string(), Format::Json).unwrap();
    let key = parse("key");
    assert_eq!(key.onset_weight(Some(40), 0.0).unwrap(), Some(0.5));
    assert_eq!(key.onset_weight(Some(i64::MAX), 0.0).unwrap(), Some(1.0));
    assert!(key.onset_weight(None, 0.0).is_err());
    let velocity = parse("velocity");
    assert_eq!(velocity.onset_weight(None, 0.0).unwrap(), Some(1.0));
    assert_eq!(velocity.onset_weight(None, 1.0).unwrap(), Some(0.0));
    let control = parse("control");
    assert_eq!(control.onset_weight(None, 0.0).unwrap(), None);
    assert_eq!(control.control_route(), Some((-0.5, 0.5, true, true)));
    assert_eq!(control.control_weight(-1.0).unwrap(), 0.0);
    assert_eq!(control.control_weight(1.0).unwrap(), 1.0);
    assert!((control.control_weight(0.0).unwrap() - 0.5_f64.sqrt()).abs() < 1e-15);
    let fades = [key, velocity, control.clone()];
    let gain = onset_gain(&fades, Some(40), 0.5, [3.0, -6.0, -17.0]).unwrap();
    assert!((gain - 0.05 * 0.5_f64.sqrt()).abs() < 1e-15);
    assert_eq!(onset_gain(&fades, Some(40), 1.0, [0.0; 3]).unwrap(), 0.0);
    assert!(onset_gain(&fades, None, 0.5, [0.0; 3]).is_err());
    assert!(onset_gain(&[], None, 0.5, [1e10, 0.0, 0.0]).is_err());
    let text = toml::to_string(&control).unwrap();
    assert_eq!(
        codec::parse_sample_crossfade(&text, Format::Toml).unwrap(),
        control
    );
    for rejected in data["rejected"].as_array().unwrap() {
        assert!(codec::parse_sample_crossfade(&rejected.to_string(), Format::Json).is_err());
    }
}

#[test]
fn live_sample_crossfade_resolves_control_domain_and_exact_frame_smoothing() {
    let data: Value =
        serde_json::from_str(include_str!("../../../conformance/sample-crossfade.json")).unwrap();
    let name = Identifier::new("expression".into()).unwrap();
    let controls = |polarity| {
        BTreeMap::from([(
            name.clone(),
            ControlDeclaration::new(polarity, 0.25).unwrap(),
        )])
    };
    let mut definition = data["control"].clone();
    definition["smoothing_seconds"] = json!(0.00003125);
    let fade = codec::parse_sample_crossfade(&definition.to_string(), Format::Json).unwrap();
    let route = fade
        .prepare_control(&controls(Polarity::Bipolar), 48_000)
        .unwrap()
        .unwrap();
    assert_eq!(route.control, &name);
    assert_eq!(route.scope, ControlScope::Trigger);
    assert_eq!((route.default, route.minimum), (0.25, -1.0));
    assert_eq!(route.smoothing_frames, Rational::new(3, 2).unwrap());
    assert_eq!(route.interval, (-0.5, 0.5));
    assert_eq!(route.shape, (true, true));

    assert!(fade.prepare_control(&BTreeMap::new(), 48_000).is_err());
    assert!(
        fade.prepare_control(&controls(Polarity::Unipolar), 48_000)
            .is_err()
    );
    definition["smoothing_seconds"] = json!(1e-20);
    let out_of_range =
        codec::parse_sample_crossfade(&definition.to_string(), Format::Json).unwrap();
    assert!(
        out_of_range
            .prepare_control(&controls(Polarity::Bipolar), 48_000)
            .is_err()
    );
}

#[test]
fn rendered_sample_steps_match_shared_vectors() {
    let data: Value =
        serde_json::from_str(include_str!("../../../conformance/sample-playback.json")).unwrap();
    for row in data["rendered_steps"].as_array().unwrap() {
        let [base, cents, layer, rate, expected]: [f64; 5] =
            serde_json::from_value(row.clone()).unwrap();
        let ratio = tuned_pitch_ratio(base, cents, layer).unwrap();
        assert_eq!(sample_step(ratio, rate).unwrap(), expected);
    }
    for row in data["invalid_rendered_steps"].as_array().unwrap() {
        let [base, cents, layer, rate]: [f64; 4] = serde_json::from_value(row.clone()).unwrap();
        assert!(
            tuned_pitch_ratio(base, cents, layer)
                .and_then(|ratio| sample_step(ratio, rate))
                .is_err()
        );
    }
}

#[test]
fn sampler_batch_bound_uses_declared_tuning_limits_in_each_layer() {
    let modulation = codec::parse_modulation(
        r#"{"parameters":[
          {"target":{"name":"operator-main","parameter":"tuning_cents"},"unit":"cents",
           "scope":"voice","minimum":-2400,"default":0,"maximum":2400},
          {"target":{"name":"processing","parameter":"tuning_cents"},"unit":"cents",
           "scope":"voice","minimum":0,"default":0,"maximum":900}
        ]}"#,
        Format::Json,
    )
    .unwrap();
    let common = maximum_tuning_cents(300.0, &[]);
    let slot = maximum_tuning_cents(0.0, modulation.parameters());
    assert_eq!((common, slot), (300.0, 900.0));
    assert_eq!(maximum_sample_step(0.5, 48_000.0, common, slot), 48_000.0);
    assert_eq!(
        maximum_sample_step(1.0, 48_000.0, 1e10, slot),
        f64::INFINITY
    );
}

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
