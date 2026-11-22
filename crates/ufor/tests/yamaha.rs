use serde_json::{Value, json};
use ufor::codec::{Format, parse_yamaha_patch, yamaha_patch_text};
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
