use serde_json::{Value, json};
use ufor::codec::{self, Format};
use ufor::envelfo::PreparationLimits;
use ufor::modulation::Target;
use ufor::samples::inheritance::resolve_slot_settings;
use ufor::samples::processing::{SoundSettings, TargetResolution};
use ufor::samples::slots::PreparedSlots;

#[test]
fn slot_categories_and_selection_match_shared_vectors() {
    // Keep the authored group JSON so the intentionally unsorted keys survive.
    let vectors: std::collections::BTreeMap<String, Box<serde_json::value::RawValue>> =
        serde_json::from_str(include_str!("../../../conformance/slot-settings.json")).unwrap();
    let cases: Vec<Value> = serde_json::from_str(vectors["cases"].get()).unwrap();
    for case in cases {
        let group = case["grouped"]
            .as_bool()
            .unwrap()
            .then(|| vectors["group"].get());
        let projected = resolve_slot_settings(&case["slot"].to_string(), group).unwrap();
        let mut slot = case["slot"].clone();
        slot["name"] = serde_json::json!("voice");
        slot["slice"] = serde_json::json!("audio");
        slot["mapping"] =
            serde_json::json!({"lowest_key":60,"highest_key":72,"reference_pitch_hz":440});
        slot["channels"] = serde_json::json!([{"input":"mono","output":"left"}]);
        let groups = if let Some(group) = group {
            slot["group"] = serde_json::json!("kit");
            let group = group.trim().strip_prefix('{').unwrap();
            format!(r#"[{{"name":"kit",{group}]"#)
        } else {
            "[]".into()
        };
        let body = format!(
            r#"{{"kind":"sample_instrument","slices":[{{"name":"audio","asset":"clip","end_frame":16}}],"slots":[{slot}],"groups":{groups},"settings":{{"selections":[{{"name":"takes","mode":"cycle"}},{{"name":"alternate","mode":"random"}}]}}}}"#,
        );
        let prepared = PreparedSlots::from_json(&body, PreparationLimits::default()).unwrap();
        let resolved = prepared.settings().values().next().unwrap();
        assert_eq!(
            serde_json::to_string(resolved).unwrap(),
            serde_json::to_string(&projected).unwrap()
        );
        let context = codec::parse_sample_eligibility_context(
            r#"{"trigger":"start","key":69,"velocity":1.0,"held_keys":[],"controls":{},"note_on_count":1,"random_value":0.0}"#,
            Format::Json,
        ).unwrap();
        assert_eq!(
            prepared.eligibility().matching_slots(&context).unwrap()[0].as_str(),
            "voice"
        );
        assert_eq!(
            resolved.selection.as_ref().map(|name| name.as_str()),
            case["selection"].as_str()
        );
        let text = serde_json::to_string(&resolved.settings).unwrap();
        let settings =
            codec::parse_sound_settings(&text, Format::Json, PreparationLimits::default()).unwrap();
        assert_eq!(
            target(&settings, "volume_db"),
            case["volume_db"].as_f64().unwrap()
        );
        assert_eq!(
            target(&settings, "tuning_cents"),
            case["tuning_cents"].as_f64().unwrap()
        );
        assert_eq!(
            settings.envelope().is_some(),
            case["envelope"].as_bool().unwrap()
        );
        let names: Vec<_> = settings
            .envelfos()
            .iter()
            .map(|(name, _)| name.as_str())
            .collect();
        assert_eq!(serde_json::json!(names), case["envelfos"]);
    }
}

#[test]
fn authored_sampler_slots_preserve_exact_play_count_and_delay() {
    let document = r#"{
        "slices":[{"name":"audio","asset":"clip","end_frame":16}],
        "settings":{"playback":{"direction":"backward","mode":"one_shot"}},
        "slots":[{
            "name":"voice","slice":"audio",
            "mapping":{"lowest_key":60,"highest_key":72,"reference_pitch_hz":440},
            "playback":{"play_count":18446744073709551616,"start_delay_seconds":"1/100000 s","end_fade_seconds":0.001}
        }]
    }"#;
    let slots = PreparedSlots::from_json(document, PreparationLimits::default()).unwrap();
    let playback = slots.playback("voice").unwrap();
    assert_eq!(
        playback.playback.mode,
        ufor::samples::playback::PlaybackMode::OneShot
    );
    assert_eq!(
        playback.playback.direction,
        ufor::samples::playback::Direction::Backward
    );
    assert_eq!(playback.additional_plays, u64::MAX);
    assert_eq!(
        playback
            .delay_frames(ufor::number::Rational::new(1, 100000).unwrap(), 48000)
            .unwrap(),
        1
    );
    assert_eq!(playback.end_fade_seconds, 0.001);
}

#[test]
fn authored_sampler_slots_reject_incompatible_playback_and_slice_declarations() {
    let body = serde_json::json!({
        "slices":[{"name":"audio","asset":"clip","end_frame":16}],
        "slots":[{"name":"voice","slice":"audio","mapping":{"lowest_key":60,"highest_key":72,"reference_pitch_hz":440}}]
    });
    for (field, value, expected) in [
        ("slice", serde_json::json!("absent"), "Unknown slice"),
        ("trigger", serde_json::json!("release"), "require one_shot"),
        (
            "playback",
            serde_json::json!({"play_count":1}),
            "play_count requires one_shot",
        ),
    ] {
        let mut document = body.clone();
        document["slots"][0][field] = value;
        let error = PreparedSlots::from_json(&document.to_string(), PreparationLimits::default())
            .unwrap_err();
        assert!(error.to_string().contains(expected), "{error}");
    }
    let mut looped = body;
    looped["slices"][0]["loop"] =
        serde_json::json!({"start_frame":2,"end_frame":12,"crossfade_frames":2});
    for (playback, expected) in [
        (
            serde_json::json!({"mode":"one_shot"}),
            "loops require while_held",
        ),
        (
            serde_json::json!({"direction":"mirror"}),
            "Mirror loops cannot crossfade",
        ),
    ] {
        looped["slots"][0]["playback"] = playback;
        let error = PreparedSlots::from_json(&looped.to_string(), PreparationLimits::default())
            .unwrap_err();
        assert!(error.to_string().contains(expected), "{error}");
    }
}

#[test]
fn authored_sampler_slots_check_references_and_prepare_controls() {
    let document = json!({
        "slices": [{"name": "audio", "asset": "clip", "end_frame": 16}],
        "settings": {
            "controls": {"pedal": {"default": 1.0}},
            "sustain": {"control": "pedal"},
            "articulations": {"ids": ["open"], "keys": [{"key": 24, "articulation": "open"}]},
            "selections": [{"name": "takes", "mode": "cycle"}]
        },
        "groups": [{"name": "kit", "selection": "takes"}],
        "slots": [{
            "name": "first", "slice": "audio", "group": "kit",
            "take": "a", "microphone": "room",
            "mapping": {"lowest_key": 60, "highest_key": 72, "reference_pitch_hz": 440},
            "articulations": ["open"],
            "control_conditions": [{"control": "pedal", "minimum_value": 0.5}],
            "choke_group": "previous",
            "chokes": [{"group": "previous", "mode": "immediate"}]
        }, {
            "name": "second", "slice": "audio", "group": "kit",
            "take": "b", "microphone": "room",
            "mapping": {"lowest_key": 60, "highest_key": 72, "reference_pitch_hz": 440}
        }]
    });
    let prepared =
        PreparedSlots::from_json(&document.to_string(), PreparationLimits::default()).unwrap();
    assert!(prepared.sustain_pressed());
    assert_eq!(prepared.latched_keys().unwrap()[0].key, 24);
    for (index, field, value, expected) in [
        (0, "selection", json!("missing"), "unknown selection"),
        (0, "voice_pool", json!("missing"), "unknown voice pool"),
        (
            0,
            "chokes",
            json!([{"group": "missing", "mode": "immediate"}]),
            "unknown choke group",
        ),
        (
            0,
            "articulations",
            json!(["missing"]),
            "unknown articulation",
        ),
        (
            0,
            "control_conditions",
            json!([{"control": "missing"}]),
            "Unknown control",
        ),
        (
            0,
            "control_conditions",
            json!([{"control": "pedal", "minimum_value": -0.5}]),
            "outside polarity domain",
        ),
        (
            0,
            "crossfades",
            json!([{"input": "key", "direction": "in", "start": 59, "end": 64}]),
            "Mapping must cover",
        ),
        (
            0,
            "crossfades",
            json!([{"input": "control", "control": "missing", "direction": "in", "start": 0.0, "end": 1.0}]),
            "Unknown crossfade control",
        ),
        (1, "take", json!("a"), "duplicate microphone"),
        (1, "microphone", json!("close"), "different microphones"),
    ] {
        let mut invalid = document.clone();
        invalid["slots"][index][field] = value;
        let error = PreparedSlots::from_json(&invalid.to_string(), PreparationLimits::default())
            .unwrap_err();
        assert!(error.to_string().contains(expected), "{error}");
    }
}

#[test]
fn sampler_layers_match_shared_spatial_bounds() {
    let vectors: Value =
        serde_json::from_str(include_str!("../../../conformance/sampler-spatial.json")).unwrap();
    for (index, case) in vectors["slots"].as_array().unwrap().iter().enumerate() {
        let body = json!({
            "slices": [{"name": "audio", "asset": "clip", "end_frame": 16}],
            "settings": vectors["instrument"],
            "groups": [{"name": "kit", "processing": case["processing"]}],
            "slots": [{
                "name": "voice", "slice": "audio", "group": "kit",
                "mapping": {"lowest_key": 60, "highest_key": 72, "reference_pitch_hz": 440}
            }]
        });
        let prepared = PreparedSlots::from_json(&body.to_string(), PreparationLimits::default());
        if case["valid"] == true {
            prepared.unwrap();
        } else {
            let target = if index < 3 { "pan" } else { "stereo_balance" };
            let error = prepared.unwrap_err();
            assert!(
                error
                    .to_string()
                    .contains(&format!("combined {target} range")),
                "{error}"
            );
        }
    }
}

#[test]
fn sampler_layers_reject_conflicting_filters_and_uncovered_keys() {
    let filter = json!({"name": "tone", "response": "lowpass", "cutoff_hz": 1000});
    let body = json!({
        "slices": [{"name": "audio", "asset": "clip", "end_frame": 16}],
        "settings": {"processing": {"filters": [filter]}},
        "slots": [{
            "name": "voice", "slice": "audio",
            "mapping": {"lowest_key": 60, "highest_key": 72, "reference_pitch_hz": 440},
            "processing": {"filters": [filter], "filter_order": "after_amplitude"}
        }]
    });
    let error =
        PreparedSlots::from_json(&body.to_string(), PreparationLimits::default()).unwrap_err();
    assert!(
        error
            .to_string()
            .contains("active filter chains require the same order"),
        "{error}"
    );
    let mut keys = body;
    keys["slots"][0]["processing"] = json!({});
    keys["slots"][0]["bindings"] = json!([{"name":"key","kind":"key"}]);
    keys["slots"][0]["modulation"] = json!({
        "sources":[{"name":"key","scope":"voice","minimum":61,"maximum":72}]
    });
    let error =
        PreparedSlots::from_json(&keys.to_string(), PreparationLimits::default()).unwrap_err();
    assert!(
        error
            .to_string()
            .contains("NoteKey source domain must cover the slot mapping"),
        "{error}"
    );
}

fn target(settings: &SoundSettings, field: &str) -> f64 {
    let target: Target =
        serde_json::from_value(serde_json::json!({"name":"processing", "parameter":field}))
            .unwrap();
    let TargetResolution::Resolved(resolved) = settings.resolve_target(&target).unwrap() else {
        panic!("processing target")
    };
    resolved.default_value
}
