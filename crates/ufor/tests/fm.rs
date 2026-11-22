use serde_json::{Value, json};
use ufor::codec::{self, Format};
use ufor::envelfo::{PreparationLimits, Waveform};
use ufor::identifier::Identifier;
use ufor::modulation::Target;
use ufor::samples::processing::TargetResolution;

#[test]
fn fm_graph_targets_and_order_follow_the_authored_definitions() {
    let corpus: Value =
        serde_json::from_str(include_str!("../../../conformance/fm-graph.json")).unwrap();
    let limits = PreparationLimits::default();
    let graph = codec::parse_fm(&corpus["graph"].to_string(), Format::Json, limits).unwrap();
    assert_eq!(json!(graph.order()), corpus["execution_order"]);
    assert_eq!(graph.operators()[0].phase_cycles(), 0.25);
    assert_eq!(graph.operators()[1].waveform(), Waveform::Sine);
    for row in corpus["targets"].as_array().unwrap() {
        let target = Target::new(
            Identifier::new(row[0].as_str().unwrap().into()).unwrap(),
            Identifier::new(row[1].as_str().unwrap().into()).unwrap(),
        );
        let facts = graph.resolve_target(&target).unwrap();
        assert_eq!(json!(facts.unit), row[2]);
        assert_eq!(facts.default_value, row[3].as_f64().unwrap());
        assert_eq!(json!(facts.minimum), row[4]);
    }
    for raw in corpus["rejected"].as_array().unwrap() {
        assert!(
            codec::parse_fm(&raw.to_string(), Format::Json, limits).is_err(),
            "{raw}"
        );
    }
    for format in [Format::Json, Format::Toml] {
        let text = codec::fm_text(&graph, format).unwrap();
        assert_eq!(codec::parse_fm(&text, format, limits).unwrap(), graph);
    }
    // Root, four operators, three edges, and one explicit Envelope with two segments.
    let text = corpus["graph"].to_string();
    assert!(codec::parse_fm(&text, Format::Json, PreparationLimits::new(11).unwrap()).is_ok());
    assert!(codec::parse_fm(&text, Format::Json, PreparationLimits::new(10).unwrap()).is_err());
}

#[test]
fn fm_voice_settings_resolve_graph_and_processing_parameters_together() {
    let corpus: Value =
        serde_json::from_str(include_str!("../../../conformance/fm-graph.json")).unwrap();
    let limits = PreparationLimits::default();
    let graph = codec::parse_fm(&corpus["graph"].to_string(), Format::Json, limits).unwrap();
    let source = &corpus["voice_settings"];
    let voice_document = |settings: &Value| {
        let mut voice = json!({
            "name": "bell",
            "mapping": {"lowest_key": 0, "highest_key": 127, "reference_pitch_hz": 440},
            "channels": [{"input": "mono", "output": "mono", "gain": 1}],
            "fm": corpus["graph"],
        });
        voice
            .as_object_mut()
            .unwrap()
            .extend(settings.as_object().unwrap().clone());
        json!({"voices": [voice]}).to_string()
    };
    let voices = codec::parse_synth_voices(&voice_document(source), Format::Json, limits).unwrap();
    let voice = &voices.voices()[0];
    for parameter in voice.settings().modulation().parameters() {
        let TargetResolution::Resolved(target) = voice.resolve_target(parameter.target()).unwrap()
        else {
            panic!("expected resolved FM voice target");
        };
        assert_eq!(target.default_value, parameter.default_value());
    }
    let resolve = |target: &Target| graph.resolve_target(target);
    let settings = codec::parse_sound_settings_with_targets(
        &source.to_string(),
        Format::Json,
        limits,
        resolve,
    )
    .unwrap();
    assert!(
        settings
            .validate_context_with_targets(None, limits, resolve)
            .unwrap()
            .is_complete()
    );
    assert!(codec::parse_sound_settings(&source.to_string(), Format::Json, limits).is_err());
    let text = codec::sound_settings_text(&settings, Format::Toml).unwrap();
    let restored =
        codec::parse_sound_settings_with_targets(&text, Format::Toml, limits, resolve).unwrap();
    assert_eq!(
        serde_json::to_value(restored).unwrap(),
        serde_json::to_value(settings).unwrap(),
    );
    for spec in corpus["invalid_settings_parameters"].as_array().unwrap() {
        let mut edited = source.clone();
        let index = spec["index"].as_u64().unwrap() as usize;
        edited["modulation"]["parameters"][index]
            .as_object_mut()
            .unwrap()
            .extend(spec["override"].as_object().unwrap().clone());
        assert!(
            codec::parse_synth_voices(&voice_document(&edited), Format::Json, limits).is_err(),
            "{spec}"
        );
        assert!(
            codec::parse_sound_settings_with_targets(
                &edited.to_string(),
                Format::Json,
                limits,
                resolve,
            )
            .is_err(),
            "{spec}"
        );
    }
}
