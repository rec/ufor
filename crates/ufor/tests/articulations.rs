use serde_json::Value;
use ufor::codec::{Format, articulations_text, parse_articulations};
use ufor::control::Polarity;
use ufor::envelfo::PreparationLimits;
use ufor::identifier::Identifier;
use ufor::samples::controls::ControlDeclaration;

const CASES: &str = include_str!("../../../conformance/articulations.json");

#[test]
fn shared_articulations_validate_and_round_trip() {
    let vectors: Value = serde_json::from_str(CASES).unwrap();
    let limits = PreparationLimits::default();
    for kind in ["latched", "controlled", "momentary"] {
        let body = parse_articulations(&vectors[kind].to_string(), Format::Json, limits).unwrap();
        let text = articulations_text(&body, Format::Toml).unwrap();
        assert_eq!(
            parse_articulations(&text, Format::Toml, limits).unwrap(),
            body
        );
    }
    for case in vectors["invalid"].as_array().unwrap() {
        assert!(
            parse_articulations(&case.to_string(), Format::Json, limits).is_err(),
            "{case}"
        );
    }
}

#[test]
fn sampler_profile_prepares_latched_switches_including_an_explicit_clear() {
    let vectors: Value = serde_json::from_str(CASES).unwrap();
    let limits = PreparationLimits::default();
    let text = vectors["latched"].to_string();
    let body = parse_articulations(&text, Format::Json, limits).unwrap();
    assert_eq!(body.default_articulation().unwrap().as_str(), "soft");
    let keys = body.latched_keys().unwrap();
    assert_eq!((keys[0].key, keys[0].consume), (24, true));
    assert_eq!(keys[0].articulation.as_ref().unwrap().as_str(), "hard");
    assert_eq!(
        (keys[1].key, keys[1].consume, &keys[1].articulation),
        (25, false, &None)
    );
    assert!(parse_articulations(&text, Format::Json, PreparationLimits::new(4).unwrap()).is_err());
    for kind in ["controlled", "momentary"] {
        let body = parse_articulations(&vectors[kind].to_string(), Format::Json, limits).unwrap();
        assert!(body.latched_keys().is_err());
    }
}

#[test]
fn articulation_endpoints_must_match_declared_control_domains() {
    let vectors: Value = serde_json::from_str(CASES).unwrap();
    let body = parse_articulations(
        &vectors["controlled"].to_string(),
        Format::Json,
        PreparationLimits::default(),
    )
    .unwrap();
    let name = Identifier::new("style".into()).unwrap();
    assert!(body.validate_controls(&Default::default()).is_err());
    let mut controls = [(name.clone(), ControlDeclaration::default())].into();
    assert!(body.validate_controls(&controls).is_err());
    controls.insert(
        name,
        ControlDeclaration::new(Polarity::Bipolar, 0.0).unwrap(),
    );
    body.validate_controls(&controls).unwrap();
}
