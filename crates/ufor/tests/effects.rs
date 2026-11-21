use serde_json::{Value, json};
use std::collections::BTreeMap;
use ufor::codec::{self, Format};
use ufor::envelfo::PreparationLimits;
use ufor::modulation::Parameter;

#[test]
fn effect_processor_targets_match_the_shared_contract() {
    let cases: Value =
        serde_json::from_str(include_str!("../../../conformance/effect-targets.json")).unwrap();
    let limits = PreparationLimits::default();
    let processors: BTreeMap<_, _> = cases["processors"]
        .as_array()
        .unwrap()
        .iter()
        .map(|value| {
            let processor =
                codec::parse_effect_processor(&value.to_string(), Format::Json, limits).unwrap();
            (processor.name().as_str().to_owned(), processor)
        })
        .collect();
    for (group, accepted) in [("accepted", true), ("rejected", false)] {
        for case in cases[group].as_array().unwrap() {
            let parameter: Parameter = serde_json::from_value(json!({
                "target": {"name": case[0], "parameter": case[1]}, "unit": case[2],
                "default": case[3], "minimum": case[4], "maximum": case[5], "scope": "voice",
            }))
            .unwrap();
            let processor = &processors[case[0].as_str().unwrap()];
            assert_eq!(
                processor.validate_parameter(&parameter).is_ok(),
                accepted,
                "{case}"
            );
            if accepted {
                let text = toml::to_string(&processor).unwrap();
                let restored = codec::parse_effect_processor(&text, Format::Toml, limits).unwrap();
                assert_eq!(&restored, processor);
                restored.validate_parameter(&parameter).unwrap();
            }
        }
    }
    for value in cases["invalid_processors"].as_array().unwrap() {
        assert!(codec::parse_effect_processor(&value.to_string(), Format::Json, limits).is_err());
    }
}
