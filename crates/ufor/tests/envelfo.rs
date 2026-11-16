//! Preparation foundations for the shared generator-definition contract.
use serde_json::{Value, json};
use ufor::codec::{self, Format};
use ufor::envelfo::{Body, ExponentialApproach, Generator, quantize_value};
use ufor::envelfo::{PreparationLimits, preparation_records};
use ufor::quantity::exact;

fn cases() -> Value {
    serde_json::from_str(include_str!(
        "../../../conformance/envelfo-definitions.json"
    ))
    .unwrap()
}

#[test]
fn exact_generator_quantities_share_the_python_contract() {
    for case in cases()["quantities"].as_array().unwrap() {
        let result = match case["input"].as_str() {
            Some(text) => exact(text, case["unit"].as_str().unwrap()),
            None => {
                assert_eq!(case["rejected"], true);
                continue;
            }
        };
        if case["rejected"] == true {
            assert!(result.is_err(), "{}", case["id"]);
        } else {
            assert_eq!(
                result.unwrap().to_string(),
                case["expected"].as_str().unwrap(),
                "{}",
                case["id"]
            );
        }
    }
}

#[test]
fn declarations_and_references_share_one_configurable_budget() {
    for case in cases()["budgets"].as_array().unwrap() {
        let count = usize::try_from(case["records"].as_u64().unwrap()).unwrap();
        assert_eq!(
            preparation_records(&case["input"], PreparationLimits::new(count).unwrap()).unwrap(),
            count,
            "{}",
            case["id"]
        );
        assert!(
            preparation_records(&case["input"], PreparationLimits::new(count - 1).unwrap())
                .is_err(),
            "{}",
            case["id"]
        );
    }
    let value = json!({"kind":"envelope", "segments": vec![json!({"duration":null}); 10000]});
    assert!(preparation_records(&value, PreparationLimits::default()).is_err());
    assert_eq!(
        preparation_records(&value, PreparationLimits::new(10001).unwrap()).unwrap(),
        10001
    );
    assert!(preparation_records(&json!({}), PreparationLimits::new(0).unwrap()).is_err());
}

#[test]
fn quantity_text_budget_has_the_same_boundary() {
    for case in cases()["quantity_text_limits"].as_array().unwrap() {
        let length = usize::try_from(case["length"].as_u64().unwrap()).unwrap();
        let text = format!("1{}", " ".repeat(length - 1));
        assert_eq!(
            exact(&text, "seconds").is_ok(),
            case["accepted"].as_bool().unwrap()
        );
    }
}

fn same(actual: &Value, expected: &Value) {
    match expected {
        Value::Object(values) => {
            for (key, value) in values {
                same(&actual[key], value);
            }
        }
        Value::Array(values) => {
            let a = actual.as_array().unwrap();
            assert_eq!(a.len(), values.len());
            for (a, e) in a.iter().zip(values) {
                same(a, e);
            }
        }
        Value::Number(v) => {
            let a = actual.as_f64().unwrap();
            let e = v.as_f64().unwrap();
            assert!(
                (a - e).abs() <= 1e-12_f64.max(e.abs() * 1e-12),
                "{a} != {e}"
            );
        }
        _ => assert_eq!(actual, expected),
    }
}

#[test]
fn shared_generator_definitions_and_roundtrips() {
    for case in cases()["definitions"].as_array().unwrap() {
        let text = serde_json::to_string(&case["input"]).unwrap();
        let result = codec::parse_generator(&text, Format::Json, PreparationLimits::default());
        if case["rejected"] == true {
            assert!(result.is_err(), "{}", case["id"]);
            continue;
        }
        let value = result.unwrap_or_else(|e| panic!("{}: {e}", case["id"]));
        if let Some(expected) = case.get("expected") {
            same(&serde_json::to_value(&value).unwrap(), expected);
        }
        if let Some(expected) = case.get("ranges") {
            let Body::Patch(patch) = value.body() else {
                panic!("expected Patch")
            };
            let ranges: std::collections::BTreeMap<_, _> = patch
                .signal_ranges()
                .iter()
                .map(|(n, r)| (n.as_str(), r))
                .collect();
            same(&serde_json::to_value(ranges).unwrap(), expected);
        }
        for format in [Format::Json, Format::Toml] {
            let text = codec::generator_text(&value, format)
                .unwrap_or_else(|e| panic!("{} write: {e}", case["id"]));
            assert_eq!(
                codec::parse_generator(&text, format, PreparationLimits::default())
                    .unwrap_or_else(|e| panic!("{} read: {e}", case["id"])),
                value,
                "{}",
                case["id"]
            );
        }
    }
}

#[test]
fn shared_quantizers_and_captured_approaches() {
    for case in cases()["quantizers"].as_array().unwrap() {
        let value = quantize_value(
            case["value"].as_f64().unwrap(),
            case["step"].as_f64().unwrap(),
            case["origin"].as_f64().unwrap(),
        )
        .unwrap();
        same(&json!(value), &case["expected"]);
    }
    for case in cases()["approaches"].as_array().unwrap() {
        let approach: ExponentialApproach = serde_json::from_value(case["input"].clone()).unwrap();
        let segments = approach.resolve(case["initial"].as_f64().unwrap()).unwrap();
        same(&serde_json::to_value(&segments).unwrap(), &case["expected"]);
        assert_eq!(
            serde_json::from_str::<ExponentialApproach>(&serde_json::to_string(&approach).unwrap())
                .unwrap(),
            approach
        );
    }
}

#[test]
fn shared_segments_and_approach_failures() {
    for case in cases()["segments"].as_array().unwrap() {
        let result = serde_json::from_value::<ufor::envelfo::Segment>(case["input"].clone());
        if case["rejected"] == true {
            assert!(result.is_err(), "{}", case["id"]);
        } else {
            same(
                &serde_json::to_value(result.unwrap()).unwrap(),
                &case["expected"],
            );
        }
    }
    for case in cases()["approach_errors"].as_array().unwrap() {
        let value: ExponentialApproach = serde_json::from_value(case["input"].clone()).unwrap();
        assert!(
            value.resolve(case["initial"].as_f64().unwrap()).is_err(),
            "{}",
            case["id"]
        );
    }
}

#[test]
fn original_document_order_survives_both_text_adapters() {
    for case in cases()["ordered_documents"].as_array().unwrap() {
        let format = if case["format"] == "json" {
            Format::Json
        } else {
            Format::Toml
        };
        let value = codec::parse_generator(
            case["text"].as_str().unwrap(),
            format,
            PreparationLimits::default(),
        )
        .unwrap();
        for format in [Format::Json, Format::Toml] {
            let text = codec::generator_text(&value, format).unwrap();
            let restored =
                codec::parse_generator(&text, format, PreparationLimits::default()).unwrap();
            let Body::Patch(patch) = restored.body() else {
                panic!("expected Patch")
            };
            assert_eq!(
                patch
                    .outputs()
                    .iter()
                    .map(|(n, _)| n.as_str())
                    .collect::<Vec<_>>(),
                case["outputs"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|v| v.as_str().unwrap())
                    .collect::<Vec<_>>(),
                "{} {format:?}: {text}",
                case["id"]
            );
        }
    }
}

#[test]
fn validation_limits_and_programmatic_reconstruction_are_checked() {
    let value = json!({"kind":"envelope","segments":vec![json!({"duration":0,"to":1});10000]});
    let text = serde_json::to_string(&value).unwrap();
    assert!(serde_json::from_str::<Generator>(&text).is_err());
    let limits = PreparationLimits::new(10001).unwrap();
    let value = codec::parse_generator(&text, Format::Json, limits).unwrap();
    assert!(
        Generator::new(
            value.settings().clone(),
            value.body().clone(),
            PreparationLimits::default()
        )
        .is_err()
    );
    assert_eq!(
        Generator::new(value.settings().clone(), value.body().clone(), limits).unwrap(),
        value
    );
    let negative = ufor::envelfo::Rate::Literal(ufor::number::Rational::new(-1, 1).unwrap());
    assert!(Generator::lfo(negative, ufor::envelfo::Settings::default(), limits).is_err());
    let text = r#"{"kind":"patch","envelfos":{"a":{"kind":"sample_hold"},"b":{"kind":"slew","input":"a","rise":"1e-200/s","fall":2}},"outputs":{"out":"b"}}"#;
    let value = codec::parse_generator(text, Format::Json, PreparationLimits::default()).unwrap();
    let Body::Patch(p) = value.body() else {
        panic!()
    };
    let ufor::envelfo::PatchNode::Signal(n) = &p.envelfos()[1].1 else {
        panic!()
    };
    let ufor::envelfo::SignalOperation::Slew { rise, .. } = n.operation() else {
        panic!()
    };
    assert_eq!(*rise, 1e-200);
}

#[test]
fn shared_text_limits_apply_before_selector_canonicalization() {
    for case in cases()["text_limits"].as_array().unwrap() {
        let mut value = case["input"].clone();
        let path = case["path"].as_array().unwrap();
        let mut target = &mut value;
        for key in &path[..path.len() - 1] {
            target = &mut target[key.as_str().unwrap()];
        }
        target[path.last().unwrap().as_str().unwrap()] =
            Value::String(" ".repeat(usize::try_from(case["length"].as_u64().unwrap()).unwrap()));
        assert_eq!(
            serde_json::from_value::<Generator>(value).is_ok(),
            case["accepted"].as_bool().unwrap(),
            "{}",
            case["id"]
        );
    }
}
