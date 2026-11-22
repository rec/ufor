use serde_json::{Value, json};
use std::collections::BTreeMap;
use ufor::codec::{self, Format};
use ufor::envelfo::PreparationLimits;
use ufor::identifier::Identifier;
use ufor::modulation::Target;
use ufor::samples::processing::{
    FilterBoundary, ResonantFilter, SoundSettings, TargetResolution, biquad_coefficients,
};

#[test]
fn biquad_respects_authored_cutoff_policy() {
    let vectors: Vec<Value> =
        serde_json::from_str(include_str!("../../../conformance/filter-cutoff.json")).unwrap();
    for case in vectors {
        let definition: ResonantFilter = serde_json::from_value(json!({
            "name": "tone", "response": case["response"], "cutoff_hz": case["cutoff"],
            "q": 1.0, "nyquist_ratio": 0.5, "boundary": case["boundary"],
        }))
        .unwrap();
        let rate = case["rate"].as_f64().unwrap();
        let bounds = definition.cutoff_bounds(rate).ok();
        assert_eq!(
            bounds,
            case["bounds"]
                .as_array()
                .map(|b| (b[0].as_f64().unwrap(), b[1].as_f64().unwrap()))
        );
        let result = biquad_coefficients(&definition, rate);
        if let Some(expected) = case["coefficients"].as_array() {
            let c = result.unwrap();
            for (actual, wanted) in [c.b0, c.b1, c.b2, c.a1, c.a2].into_iter().zip(expected) {
                assert!((actual - wanted.as_f64().unwrap()).abs() < 1e-14);
            }
        } else {
            assert!(result.is_err());
        }
    }
    assert_eq!(FilterBoundary::Clamp.resolve(0.5, 1.0, 12000.0), Some(1.0));
    assert_eq!(
        FilterBoundary::Clamp.resolve(f64::INFINITY, 1.0, 12000.0),
        None
    );
}

fn target(pair: &[Value]) -> Target {
    Target::new(
        Identifier::new(pair[0].as_str().unwrap().into()).unwrap(),
        Identifier::new(pair[1].as_str().unwrap().into()).unwrap(),
    )
}

fn parse(data: &Value, records: usize) -> Result<SoundSettings, ufor::error::Error> {
    codec::parse_sound_settings(
        &data.to_string(),
        Format::Json,
        PreparationLimits::new(records).unwrap(),
    )
}

#[test]
fn large_settings_use_one_configurable_budget() {
    let cases: Value =
        serde_json::from_str(include_str!("../../../conformance/sound-settings.json")).unwrap();
    let budget = &cases["budget"];
    let bands = budget["band_count"].as_u64().unwrap() as usize;
    let records = budget["records"].as_u64().unwrap() as usize;
    let equalizer: Vec<_> = (0..bands)
        .map(|i| {
            json!({
                "name": format!("band-{i}"), "frequency_hz": 20, "gain_db": 0, "resonance": 1,
            })
        })
        .collect();
    let data = json!({"processing": {"equalizer": equalizer}});
    assert!(parse(&data, 10000).is_err());
    let settings = parse(&data, records).unwrap();
    assert_eq!(settings.processing().equalizer().len(), bands);
    settings
        .validate_context(None, PreparationLimits::new(records).unwrap())
        .unwrap()
        .require_complete()
        .unwrap();
}

#[test]
fn shared_sound_settings_cases() {
    let cases: Value =
        serde_json::from_str(include_str!("../../../conformance/sound-settings.json")).unwrap();
    for case in cases["rejected"].as_array().unwrap() {
        assert!(parse(&case["input"], 10000).is_err(), "{}", case["id"]);
    }
    // Read the original text so the fixture parser also preserves ordered maps.
    let cases: toml::Value = toml::from_str(include_str!(
        "../../../conformance/sound-settings-order.toml"
    ))
    .unwrap();
    let text = toml::to_string(&cases).unwrap();
    let ordered =
        codec::parse_sound_settings(&text, Format::Toml, PreparationLimits::default()).unwrap();
    assert_eq!(
        ordered
            .envelfos()
            .iter()
            .map(|(n, _)| n.as_str())
            .collect::<Vec<_>>(),
        ["z-beat", "a-held"]
    );

    let cases: Value =
        serde_json::from_str(include_str!("../../../conformance/sound-settings.json")).unwrap();
    for case in cases["accepted"].as_array().unwrap() {
        let input = &case["input"];
        let limits = PreparationLimits::default();
        let settings = parse(input, 10000).unwrap_or_else(|e| panic!("{}: {e}", case["id"]));
        if let Some(count) = case["records"].as_u64() {
            assert!(parse(input, count as usize).is_ok(), "{}", case["id"]);
            assert!(parse(input, count as usize - 1).is_err(), "{}", case["id"]);
        }
        let checks = settings.validate_context(None, limits).unwrap();
        let pending: Vec<_> = checks
            .generator_checks
            .unresolved_targets()
            .iter()
            .map(|t| json!([t.name().as_str(), t.parameter().as_str()]))
            .collect();
        let controls: Vec<_> = checks
            .unresolved_controls
            .iter()
            .map(Identifier::as_str)
            .collect();
        assert_eq!(
            json!(pending),
            case.get("unresolved_targets").cloned().unwrap_or(json!([]))
        );
        assert_eq!(
            json!(controls),
            case.get("unresolved_controls")
                .cloned()
                .unwrap_or(json!([]))
        );
        assert_eq!(
            checks.require_complete().is_ok(),
            pending.is_empty() && controls.is_empty()
        );
        if !case["controls"].is_null() {
            let controls = serde_json::from_value(case["controls"].clone()).unwrap();
            let wrong = serde_json::from_value(case["wrong_controls"].clone()).unwrap();
            settings
                .validate_context(Some(&controls), limits)
                .unwrap()
                .require_complete()
                .unwrap();
            assert!(settings.validate_context(Some(&wrong), limits).is_err());
            assert!(
                settings
                    .validate_context(Some(&BTreeMap::new()), limits)
                    .is_err()
            );
            let count = case["records"].as_u64().unwrap() as usize;
            assert!(
                settings
                    .validate_context(Some(&controls), PreparationLimits::new(count).unwrap())
                    .is_err()
            );
            assert!(
                settings
                    .validate_context(Some(&controls), PreparationLimits::new(count + 1).unwrap())
                    .is_ok()
            );
        }
        if !case["materialized"].is_null() {
            let mut input = input.clone();
            input["envelfos"] = case["materialized"].clone();
            parse(&input, 10000)
                .unwrap()
                .validate_context(None, limits)
                .unwrap()
                .require_complete()
                .unwrap();
            input["envelfos"] = case["incompatible"].clone();
            assert!(parse(&input, 10000).is_err());
        }
        for format in [Format::Json, Format::Toml] {
            let text = codec::sound_settings_text(&settings, format).unwrap();
            let restored = codec::parse_sound_settings(&text, format, limits)
                .unwrap_or_else(|e| panic!("{}: {e}\n{text}", case["id"]));
            assert_eq!(restored.validate_context(None, limits).unwrap(), checks);
            assert_eq!(restored.processing(), settings.processing());
            assert_eq!(restored.modulation(), settings.modulation());
            for entry in case["targets"].as_array().into_iter().flatten() {
                let entry = entry.as_array().unwrap();
                let address = target(entry);
                let Ok(TargetResolution::Resolved(value)) = restored.resolve_target(&address)
                else {
                    panic!("{address:?}")
                };
                assert_eq!(value.unit.as_str(), entry[2].as_str().unwrap());
                assert_eq!(value.default_value, entry[3].as_f64().unwrap());
                assert_eq!(
                    value.duration.map(|v| v.to_string()).as_deref(),
                    entry.get(4).and_then(Value::as_str)
                );
                assert_eq!(
                    serde_json::to_value(value.scope).unwrap().as_str(),
                    entry.get(5).and_then(Value::as_str)
                );
            }
            for entry in case["unknown"].as_array().into_iter().flatten() {
                assert!(
                    restored
                        .resolve_target(&target(entry.as_array().unwrap()))
                        .is_err()
                );
            }
            if let Some(order) = case.get("filter_order") {
                assert_eq!(
                    &json!(
                        restored
                            .processing()
                            .filters()
                            .iter()
                            .map(|f| f.name().as_str())
                            .collect::<Vec<_>>()
                    ),
                    order
                );
            }
        }
    }
}
