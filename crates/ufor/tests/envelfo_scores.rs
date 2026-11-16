use serde::Deserialize;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use ufor::codec::{self, Format};
use ufor::envelfo::{Body, EnvelfoScore, Generator, ParameterValue, PreparationLimits, Settings};
use ufor::identifier::Identifier;
use ufor::modulation::Modulation;
use ufor::samples::bindings::validate_generator_bindings;
use ufor::samples::controls::ControlDeclaration;
use ufor::samples::processing::{Binding, EnvelfoEventConnection};
use ufor::score::Score;

fn cases() -> Value {
    serde_json::from_str(include_str!(
        "../../../conformance/envelfo-scores-bindings.json"
    ))
    .unwrap()
}

fn settings(value: &Value) -> Settings {
    let mut input = value.clone();
    input["kind"] = json!("lfo");
    input["rate"] = json!(1);
    serde_json::from_value::<Generator>(input)
        .unwrap()
        .settings()
        .clone()
}

fn subset(actual: &Value, expected: &Value) {
    match expected {
        Value::Object(v) => {
            for (k, v) in v {
                subset(&actual[k], v);
            }
        }
        _ => assert_eq!(actual, expected),
    }
}

#[test]
fn shared_score_contract_and_interchange() {
    for case in cases()["scores"].as_array().unwrap() {
        let text = case["input"].to_string();
        let result = codec::parse_score(&text, Format::Json, PreparationLimits::default());
        if case["rejected"] == true {
            assert!(result.is_err(), "{}", case["id"]);
            assert!(serde_json::from_value::<EnvelfoScore>(case["input"].clone()).is_err());
            continue;
        }
        let score = result.unwrap_or_else(|e| panic!("{}: {e}", case["id"]));
        subset(&serde_json::to_value(&score).unwrap(), &case["expected"]);
        for format in [Format::Json, Format::Toml] {
            let text = codec::score_text(&score, format).unwrap();
            assert_eq!(
                codec::parse_score(&text, format, PreparationLimits::default()).unwrap(),
                score
            );
        }
    }
}

#[test]
fn shared_parameter_materialization() {
    let data = cases();
    let score: EnvelfoScore = serde_json::from_value(data["parameterized_score"].clone()).unwrap();
    for case in data["instantiations"].as_array().unwrap() {
        let values =
            serde_json::from_value::<BTreeMap<Identifier, ParameterValue>>(case["values"].clone());
        let result = values.map_err(|e| e.to_string()).and_then(|values| {
            score
                .instantiate(
                    &values,
                    settings(&case["settings"]),
                    PreparationLimits::default(),
                )
                .map_err(|e| e.to_string())
        });
        if case["rejected"] == true {
            assert!(result.is_err(), "{}", case["id"]);
        } else {
            let generator = result.unwrap_or_else(|e| panic!("{}: {e}", case["id"]));
            subset(&serde_json::to_value(generator).unwrap(), &case["expected"]);
        }
    }
}

#[derive(Deserialize)]
struct BindingInput {
    modulation: Modulation,
    #[serde(default)]
    bindings: Vec<Binding>,
    #[serde(default)]
    controls: BTreeMap<Identifier, ControlDeclaration>,
    #[serde(default)]
    envelfos: BTreeMap<Identifier, Generator>,
    #[serde(default)]
    event_connections: Vec<EnvelfoEventConnection>,
}

#[test]
fn shared_binding_facts_and_outstanding_checks() {
    for case in cases()["bindings"].as_array().unwrap() {
        let result = serde_json::from_value::<BindingInput>(case["input"].clone())
            .map_err(|e| e.to_string())
            .and_then(|input| {
                validate_generator_bindings(
                    &input.modulation,
                    &input.bindings,
                    &input.controls,
                    &input.envelfos,
                    &input.event_connections,
                    PreparationLimits::default(),
                )
                .map_err(|e| e.to_string())
            });
        if case["rejected"] == true {
            assert!(result.is_err(), "{}", case["id"]);
        } else {
            assert_eq!(
                serde_json::to_value(result.unwrap_or_else(|e| panic!("{}: {e}", case["id"])))
                    .unwrap(),
                case["expected"],
                "{}",
                case["id"]
            );
        }
    }
}

#[test]
fn shared_event_connection_quantities_and_types() {
    for case in cases()["connections"].as_array().unwrap() {
        let result = serde_json::from_value::<EnvelfoEventConnection>(case["input"].clone());
        if case["rejected"] == true {
            assert!(result.is_err(), "{}", case["id"]);
        } else {
            assert_eq!(
                serde_json::to_value(result.unwrap()).unwrap(),
                case["expected"],
                "{}",
                case["id"]
            );
        }
    }
}

#[test]
fn score_codec_preserves_order_and_materialization_inherits_settings() {
    let data = cases();
    let limits = PreparationLimits::default();
    let score = codec::parse_score(
        data["ordered_score"].as_str().unwrap(),
        Format::Toml,
        limits,
    )
    .unwrap();
    for format in [Format::Json, Format::Toml] {
        let text = codec::score_text(&score, format).unwrap();
        let Score::Envelfo(restored) = codec::parse_score(&text, format, limits).unwrap() else {
            panic!("expected envelfo");
        };
        let Body::Patch(patch) = restored.body().body() else {
            panic!("expected patch");
        };
        assert_eq!(
            patch
                .outputs()
                .iter()
                .map(|(n, _)| n.as_str())
                .collect::<Vec<_>>(),
            ["z", "a"]
        );
        let settings = settings(&json!({"scope":"part","clock":"beats"}));
        let generator = restored
            .instantiate(&BTreeMap::new(), settings, limits)
            .unwrap();
        let normalized = serde_json::to_value(&generator).unwrap();
        assert_eq!(normalized["scope"], "part");
        assert_eq!(normalized["clock"], "beats");
        // Reparse canonical output to verify inherited settings, not only the wire omission.
        assert_eq!(
            serde_json::from_str::<Generator>(&serde_json::to_string(&generator).unwrap()).unwrap(),
            generator
        );
    }
}

#[test]
fn score_limits_and_embedded_modulation_share_the_override() {
    let score: EnvelfoScore =
        serde_json::from_value(cases()["parameterized_score"].clone()).unwrap();
    let count = ufor::envelfo::preparation_records(
        &serde_json::to_value(&score).unwrap(),
        PreparationLimits::default(),
    )
    .unwrap();
    let values = BTreeMap::from([(
        Identifier::new("speed".into()).unwrap(),
        ParameterValue::Number(2.0),
    )]);
    assert!(
        score
            .instantiate(
                &values,
                Settings::default(),
                PreparationLimits::new(count).unwrap()
            )
            .is_err()
    );
    assert!(
        score
            .instantiate(
                &values,
                Settings::default(),
                PreparationLimits::new(count + 1).unwrap()
            )
            .is_ok()
    );
    let sources: Vec<Value> = (0..10001)
        .map(|i| json!({"name":format!("s{i}"),"scope":"voice","minimum":0,"maximum":1}))
        .collect();
    let data = json!({"sources":sources});
    assert!(serde_json::from_value::<Modulation>(data.clone()).is_err());
    let definition = Modulation::decode(data, 30000).unwrap();
    let bindings = definition
        .sources()
        .iter()
        .map(|s| serde_json::from_value(json!({"kind":"velocity","name":s.name()})).unwrap())
        .collect::<Vec<_>>();
    assert!(
        validate_generator_bindings(
            &definition,
            &bindings,
            &BTreeMap::new(),
            &BTreeMap::new(),
            &[],
            PreparationLimits::default()
        )
        .is_err()
    );
    assert!(
        validate_generator_bindings(
            &definition,
            &bindings,
            &BTreeMap::new(),
            &BTreeMap::new(),
            &[],
            PreparationLimits::new(30000).unwrap()
        )
        .unwrap()
        .unresolved_bindings()
        .is_empty()
    );
}
