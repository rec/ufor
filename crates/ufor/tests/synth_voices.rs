use serde_json::{Value, json};
use ufor::codec::{Format, parse_synth_voices};
use ufor::envelfo::{Body, PreparationLimits};
use ufor::number::Rational;
use ufor::samples::eligibility::Trigger;
use ufor::synth::{NoiseKind, VoiceSource};

const CASES: &str = include_str!("../../../conformance/synth-voice-sources.json");

#[test]
fn shared_synth_sources_keep_order_and_round_trip() {
    let vectors: Value = serde_json::from_str(CASES).unwrap();
    let fields = vectors["template"].as_object().unwrap();
    let voices: Vec<_> = vectors["sources"]
        .as_array()
        .unwrap()
        .iter()
        .map(|source| {
            let mut voice = fields.clone();
            voice.extend(source.as_object().unwrap().clone());
            voice
        })
        .collect();
    let document = json!({"voices": voices});
    let limits = PreparationLimits::default();
    let prepared = parse_synth_voices(&document.to_string(), Format::Json, limits).unwrap();
    let matches: Vec<_> = prepared
        .matching_voices(Trigger::Start, 60, 1.0)
        .map(|name| name.as_str())
        .collect();
    assert_eq!(matches, ["osc", "noise", "fm"]);
    let VoiceSource::Oscillator {
        oscillator,
        synchronize_oscillator,
    } = prepared.voices()[0].source()
    else {
        panic!("expected oscillator");
    };
    assert!(*synchronize_oscillator);
    assert_eq!(oscillator.duty_cycle(), Rational::new(1, 3).unwrap());
    let Body::Envelope(envelope) = prepared.voices()[0].settings().envelope().unwrap().body()
    else {
        panic!("expected envelope")
    };
    assert_eq!(
        (envelope.segments().len(), envelope.release().len()),
        (1, 1)
    );
    assert!(matches!(
        prepared.voices()[1].source(),
        VoiceSource::Noise {
            noise: NoiseKind::White,
            ..
        }
    ));
    let VoiceSource::Fm { fm } = prepared.voices()[2].source() else {
        panic!("expected FM")
    };
    assert_eq!(fm.order(), [0, 1]);
    let text = toml::to_string(&prepared).unwrap();
    let restored = parse_synth_voices(&text, Format::Toml, limits).unwrap();
    assert_eq!(
        serde_json::to_value(restored).unwrap(),
        serde_json::to_value(&prepared).unwrap()
    );
    assert!(parse_synth_voices(&text, Format::Toml, PreparationLimits::new(10).unwrap()).is_err());
    for spec in vectors["invalid_overrides"].as_array().unwrap() {
        let mut voice = voices[spec["voice"].as_u64().unwrap() as usize].clone();
        voice.extend(spec["data"].as_object().unwrap().clone());
        let text = json!({"voices":[voice]}).to_string();
        assert!(
            parse_synth_voices(&text, Format::Json, limits).is_err(),
            "{spec}"
        );
    }
}

#[test]
fn synth_voices_keep_generator_order_and_share_one_record_budget() {
    let text = r#"{"voices":[{
        "name":"voice",
        "mapping":{"lowest_key":60,"highest_key":72,"pitch_tracking":false},
        "channels":[{"input":"mono","output":"left","gain":1}],
        "noise":"white",
        "envelfos":{
            "z":{"kind":"envelope","segments":[{"duration":"0 s","to":1}]},
            "a":{"kind":"envelope","segments":[{"duration":"0 s","to":1}]}
        }
    }]}"#;
    let limits = PreparationLimits::new(11).unwrap();
    let voices = parse_synth_voices(text, Format::Json, limits).unwrap();
    let names = |voices: &ufor::synth::SynthVoices| {
        voices.voices()[0]
            .settings()
            .envelfos()
            .iter()
            .map(|(name, _)| name.as_str().to_owned())
            .collect::<Vec<_>>()
    };
    assert_eq!(names(&voices), ["z", "a"]);
    let toml = toml::to_string(&voices).unwrap();
    let restored = parse_synth_voices(&toml, Format::Toml, limits).unwrap();
    assert_eq!(names(&restored), ["z", "a"]);
    assert!(parse_synth_voices(text, Format::Json, PreparationLimits::new(10).unwrap()).is_err());
}
