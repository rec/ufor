use serde_json::{Value, json};
use ufor::codec::{
    Format, parse_synth_instrument, parse_yamaha_patch, synth_instrument_text, yamaha_patch_text,
};
use ufor::envelfo::PreparationLimits;
use ufor::score::Score;
use ufor::synth::VoiceSource;
use ufor::yamaha::Patch;

#[test]
fn shared_instrument_patches_round_trip_as_yamaha_edit_buffers() {
    for instrument in [
        include_str!("../../../conformance/tx81z-output.json"),
        include_str!("../../../conformance/wt11-instrument.json"),
    ] {
        let score: Value = serde_json::from_str(instrument).unwrap();
        let voice = &score["body"]["voices"][0];
        let mut wire = json!({
            "yamaha": voice["yamaha"],
            "patch": voice["patch"],
            "additional": voice["additional"],
        });
        if let Some(additional2) = voice.get("additional2") {
            wire["additional2"] = additional2.clone();
        }
        let patch = parse_yamaha_patch(&wire.to_string(), Format::Json).unwrap();
        assert_eq!(patch.parameter_diagnostic(), None);
        assert_eq!(
            serde_json::from_str::<Value>(&yamaha_patch_text(&patch, Format::Json).unwrap())
                .unwrap(),
            wire
        );
        let toml = yamaha_patch_text(&patch, Format::Toml).unwrap();
        assert_eq!(parse_yamaha_patch(&toml, Format::Toml).unwrap(), patch);
    }
}

#[test]
fn dx7_keeps_packed_and_unpacked_bytes_and_reports_invalid_parameters() {
    for (length, width, algorithm, title) in [(128, 17, 110, 118), (155, 21, 134, 145)] {
        let mut bytes = vec![0; length];
        bytes[algorithm] = 31;
        bytes[title..title + 10].copy_from_slice(b"DX7 patch ");
        // The last operator block is OP1 in both dump layouts.
        bytes[5 * width + 8] = 100;
        let patch = Patch::dx7(&bytes).unwrap();
        let Patch::Dx7(voice) = &patch else {
            panic!("expected DX7");
        };
        assert_eq!(voice.packed(), length == 128);
        assert_eq!(voice.algorithm(), 32);
        assert_eq!(voice.title(), "DX7 patch ");
        assert_eq!(voice.data(), bytes);
        assert_eq!(
            patch.parameter_diagnostic().as_deref(),
            Some("DX7 operator 1 has invalid breakpoint")
        );
        assert_eq!(
            parse_yamaha_patch(
                &yamaha_patch_text(&patch, Format::Toml).unwrap(),
                Format::Toml
            )
            .unwrap(),
            patch
        );
    }
}

#[test]
fn tx81z_and_wt11_report_the_same_invalid_byte_in_different_operator_orders() {
    let voice = [0; 93];
    let mut additional = [0; 23];
    additional[5 + 3] = 8;
    for (patch, expected) in [
        (
            Patch::tx81z(&voice, &additional).unwrap(),
            "TX81Z additional operator 3 has invalid waveform",
        ),
        (
            Patch::wt11(&voice, &additional, &[0; 10]).unwrap(),
            "WT11 additional operator 2 has invalid waveform",
        ),
    ] {
        assert_eq!(patch.parameter_diagnostic().as_deref(), Some(expected));
    }
    let mut aftertouch = [0; 10];
    aftertouch[2] = 101;
    let patch = Patch::wt11(&voice, &[0; 23], &aftertouch).unwrap();
    assert_eq!(
        patch.parameter_diagnostic().as_deref(),
        Some("WT11 aftertouch has invalid pitch_bias")
    );
}

#[test]
fn malformed_wire_bytes_fail_and_hex_normalizes_like_python() {
    let mut bytes = [0; 128];
    bytes[0] = 128;
    assert!(Patch::dx7(&bytes).is_err());
    assert!(Patch::tx81z(&[0; 93], &[0; 22]).is_err());
    assert!(Patch::wt11(&[0; 93], &[0; 23], &[0; 11]).is_err());
    let malformed = json!({"yamaha": "dx7", "patch": "0 0".repeat(128)});
    assert!(parse_yamaha_patch(&malformed.to_string(), Format::Json).is_err());
    let separated = json!({"yamaha":"dx7","patch":"0A\t".repeat(128)});
    assert_eq!(
        parse_yamaha_patch(&separated.to_string(), Format::Json).unwrap(),
        Patch::dx7(&[10; 128]).unwrap()
    );
}

#[test]
fn shared_yamaha_instruments_preserve_patches_and_routing() {
    for (text, outputs, lfos) in [
        (include_str!("../../../conformance/tx81z-output.json"), 1, 0),
        (include_str!("../../../conformance/tx81z-lfo.json"), 1, 1),
        (
            include_str!("../../../conformance/wt11-instrument.json"),
            0,
            0,
        ),
    ] {
        let score: Value = serde_json::from_str(text).unwrap();
        let limits = PreparationLimits::default();
        let body =
            parse_synth_instrument(&score["body"].to_string(), Format::Json, limits).unwrap();
        let VoiceSource::Yamaha { patch, .. } = body.voices().voices()[0].source() else {
            panic!("expected Yamaha source");
        };
        assert_eq!(patch.parameter_diagnostic(), None);
        assert_eq!(body.tx81z_outputs().len(), outputs);
        assert_eq!(body.tx81z_lfos().len(), lfos);
        for format in [Format::Json, Format::Toml] {
            let text = synth_instrument_text(&body, format).unwrap();
            let restored = parse_synth_instrument(&text, format, limits).unwrap();
            assert_eq!(
                serde_json::to_value(restored).unwrap(),
                serde_json::to_value(&body).unwrap()
            );
        }
    }
}

#[test]
fn tx81z_instruments_require_valid_output_membership_and_lfo_owners() {
    let score: Value =
        serde_json::from_str(include_str!("../../../conformance/tx81z-lfo.json")).unwrap();
    for (field, invalid, expected) in [
        ("/tx81z_outputs", json!([]), "Unrouted TX81Z voices"),
        (
            "/tx81z_outputs/0/voices/0",
            json!("missing"),
            "existing TX81Z templates",
        ),
        (
            "/tx81z_lfos/0/first",
            json!("missing"),
            "owners must be group members",
        ),
        (
            "/tx81z_lfos/0/routes/patch",
            json!("second"),
            "routing requires an owner",
        ),
    ] {
        let mut body = score["body"].clone();
        *body.pointer_mut(field).unwrap() = invalid;
        let error = parse_synth_instrument(
            &body.to_string(),
            Format::Json,
            PreparationLimits::default(),
        )
        .unwrap_err();
        assert!(error.to_string().contains(expected), "{error}");
    }
}

#[test]
fn shared_synth_scores_preserve_the_port_contract_and_body() {
    let limits = PreparationLimits::default();
    for text in [
        include_str!("../../../conformance/tx81z-output.json"),
        include_str!("../../../conformance/tx81z-lfo.json"),
        include_str!("../../../conformance/wt11-instrument.json"),
    ] {
        let score = ufor::codec::parse_score(text, Format::Json, limits).unwrap();
        let Score::SynthInstrument(instrument) = &score else {
            panic!("expected a synth instrument score");
        };
        assert_eq!(instrument.output().stream.channels, ["left", "right"]);
        assert_eq!(
            instrument.timebases()[0].name(),
            &instrument.input().stream.timebase
        );
        for format in [Format::Json, Format::Toml] {
            let serialized = ufor::codec::score_text(&score, format).unwrap();
            assert_eq!(
                ufor::codec::parse_score(&serialized, format, limits).unwrap(),
                score
            );
        }
    }
}

#[test]
fn synth_scores_reject_inconsistent_ports_and_shared_output_routes() {
    let score: Value =
        serde_json::from_str(include_str!("../../../conformance/tx81z-output.json")).unwrap();
    let limits = PreparationLimits::default();
    for (field, invalid, expected) in [
        (
            "/inputs/0/stream/timebase",
            json!("missing"),
            "unknown timebase",
        ),
        (
            "/inputs/0/stream/kinds/0",
            json!("release"),
            "native performance events",
        ),
        (
            "/outputs/0/stream/channels",
            json!(["left", "left"]),
            "distinct nonempty channel names",
        ),
        (
            "/body/tx81z_outputs/0/channels/0/output",
            json!("center"),
            "mono input and known outputs",
        ),
    ] {
        let mut document = score.clone();
        *document.pointer_mut(field).unwrap() = invalid;
        let error =
            ufor::codec::parse_score(&document.to_string(), Format::Json, limits).unwrap_err();
        assert!(error.to_string().contains(expected), "{error}");
    }
}

#[test]
fn synth_scores_count_the_envelope_and_body_under_one_budget() {
    let text = include_str!("../../../conformance/tx81z-output.json");
    let score: Value = serde_json::from_str(text).unwrap();
    let body = score["body"].to_string();
    let required = (1..100)
        .find(|&records| {
            parse_synth_instrument(
                &body,
                Format::Json,
                PreparationLimits::new(records).unwrap(),
            )
            .is_ok()
        })
        .unwrap();
    for (records, accepted) in [(required + 7, false), (required + 8, true)] {
        assert_eq!(
            ufor::codec::parse_score(text, Format::Json, PreparationLimits::new(records).unwrap())
                .is_ok(),
            accepted,
        );
    }
}

#[test]
fn dx7_instrument_keeps_performance_settings_and_rejects_a_second_envelope() {
    let mut body = json!({"voices":[{
        "name":"dx7", "yamaha":"dx7", "patch":"00".repeat(155),
        "mapping":{"lowest_key":0,"highest_key":127,"reference_pitch_hz":440},
        "channels":[{"input":"mono","output":"left","gain":1}],
        "performance":{"pitch_bend_range":12,"breath":{"range":35,"pitch":true}}
    }]});
    let parse = |value: &Value| {
        parse_synth_instrument(
            &value.to_string(),
            Format::Json,
            PreparationLimits::default(),
        )
    };
    let instrument = parse(&body).unwrap();
    let VoiceSource::Yamaha {
        performance: Some(performance),
        ..
    } = instrument.voices().voices()[0].source()
    else {
        panic!("expected DX7 performance settings");
    };
    assert_eq!(performance.pitch_bend_range, 12);
    assert!(performance.breath.pitch);
    assert_eq!(performance.breath.range, 35);
    body["voices"][0]["performance"]["pitch_bend_range"] = json!(13);
    assert!(parse(&body).is_err());
    body["voices"][0]["performance"]["pitch_bend_range"] = json!(2);
    body["voices"][0]["envelope"] = json!({"segments":[{"duration":"0 s","to":1}]});
    assert!(
        parse(&body)
            .unwrap_err()
            .to_string()
            .contains("patch operator envelopes")
    );
}
