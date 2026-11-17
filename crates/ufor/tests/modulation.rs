use serde::{Serialize, de::DeserializeOwned};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fmt::Debug;
use ufor::codec::{self, Format};
use ufor::error::Error;
use ufor::identifier::Identifier;
use ufor::modulation::math::{self, CalculationError, Mapping};
use ufor::modulation::{
    self, Modulation, Parameter, ParameterValue, Point, Route, Source, SourceValue, Target,
};
use ufor::quantity;
use ufor::samples::controls::ControlDeclaration;
use ufor::samples::processing::{
    self, Binding, ControlBinding, EventBinding, FollowerBinding, GeneratorBinding,
};

fn data() -> Value {
    serde_json::from_str(include_str!("../../../conformance/modulation.json")).unwrap()
}
fn same(actual: &Value, expected: &Value, exact: bool) {
    match expected {
        Value::Object(map) => {
            assert_eq!(actual.as_object().unwrap().len(), map.len());
            for (k, v) in map {
                same(&actual[k], v, exact);
            }
        }
        Value::Array(values) => {
            assert_eq!(actual.as_array().unwrap().len(), values.len());
            for (a, e) in actual.as_array().unwrap().iter().zip(values) {
                same(a, e, exact);
            }
        }
        Value::Number(n) => {
            let (a, e) = (actual.as_f64().unwrap(), n.as_f64().unwrap());
            if exact {
                assert_eq!(a, e);
            } else {
                assert!(
                    (a - e).abs() <= 1e-12_f64.max(e.abs() * 1e-12),
                    "{a} != {e}"
                );
            }
        }
        _ => assert_eq!(actual, expected),
    }
}
fn roundtrip<T: DeserializeOwned + Serialize + PartialEq + Debug>(
    input: Value,
) -> Result<Value, String> {
    let value: T = serde_json::from_value(input).map_err(|e| e.to_string())?;
    let json = serde_json::to_value(&value).unwrap();
    assert_eq!(serde_json::from_value::<T>(json.clone()).unwrap(), value);
    let text = toml::to_string(&value).unwrap();
    assert_eq!(toml::from_str::<T>(&text).unwrap(), value);
    Ok(json)
}
fn definition(model: &str, input: Value) -> Result<Value, String> {
    match model {
        "modulation" => roundtrip::<Modulation>(input),
        "parameter" => roundtrip::<Parameter>(input),
        "source" => roundtrip::<Source>(input),
        "route" => roundtrip::<Route>(input),
        "source_value" => roundtrip::<SourceValue>(input),
        "control" => roundtrip::<ControlDeclaration>(input),
        "event_binding" => roundtrip::<EventBinding>(input),
        "control_binding" => roundtrip::<ControlBinding>(input),
        "generator_binding" => roundtrip::<GeneratorBinding>(input),
        "follower_binding" => roundtrip::<FollowerBinding>(input),
        "binding" => roundtrip::<Binding>(input),
        model => panic!("unknown model {model}"),
    }
}
#[test]
fn shared_definitions_and_interchange() {
    for case in data()["definitions"].as_array().unwrap() {
        let result = definition(case["model"].as_str().unwrap(), case["input"].clone());
        if case["rejected"] == true {
            assert!(result.is_err(), "{}", case["id"]);
        } else {
            let normalized = result.unwrap_or_else(|e| panic!("{}: {e}", case["id"]));
            if !case["normalized"].is_null() {
                same(&normalized, &case["normalized"], false);
            }
        }
    }
}
#[test]
fn shared_mapping_boundaries_and_arithmetic_errors() {
    for case in data()["maps"].as_array().unwrap() {
        let route: Route = serde_json::from_value(case["route"].clone()).unwrap();
        for query in case["queries"].as_array().unwrap() {
            let value = query["value"]
                .as_f64()
                .unwrap_or_else(|| query["value"].as_str().unwrap().parse().unwrap());
            let result = modulation::map_value(&route, value);
            let prepared = Mapping::new(route.interpolation(), route.points().to_vec()).unwrap();
            assert_eq!(prepared.value(value).is_ok(), result.is_ok());
            if let Ok(expected) = result.as_ref() {
                assert_eq!(prepared.value(value).unwrap(), *expected);
            }
            if query["error"] == "arithmetic-range" {
                assert_eq!(result, Err(Error::ArithmeticRange), "{}", case["id"]);
            } else {
                same(&json!(result.unwrap()), &query["expected"], false);
            }
        }
    }
}

#[test]
fn prepared_scalar_kernels_check_arithmetic_and_caller_storage() {
    let mapping = Mapping::new(
        modulation::Interpolation::Linear,
        vec![
            Point::new(-f64::MAX, 0.0).unwrap(),
            Point::new(f64::MAX, 1.0).unwrap(),
        ],
    )
    .unwrap();
    assert_eq!(mapping.value(-f64::MAX), Ok(0.0));
    assert_eq!(mapping.value(0.0), Err(CalculationError::NonFinite));
    assert_eq!(mapping.value(f64::NAN), Err(CalculationError::NonFinite));
    let mut storage = [0.0; 3];
    let mut count = 0;
    for value in [1e16, 1.0, -1e16] {
        math::add_partial(&mut storage, &mut count, value).unwrap();
    }
    assert_eq!(math::sum_partials(&storage[..count]), Ok(1.0));
    assert_eq!(
        math::add_partial(&mut [], &mut 0, 1.0),
        Err(CalculationError::ScratchCapacity)
    );
    let mut count = 0;
    math::add_partial(&mut storage, &mut count, f64::MAX).unwrap();
    assert_eq!(
        math::add_partial(&mut storage, &mut count, f64::MAX),
        Err(CalculationError::NonFinite)
    );
}
#[test]
fn shared_scalar_combination_and_route_permutations() {
    for case in data()["evaluations"].as_array().unwrap() {
        let definition: Modulation = serde_json::from_value(case["input"].clone()).unwrap();
        let values: BTreeMap<Identifier, SourceValue> =
            serde_json::from_value(case["values"].clone()).unwrap();
        let bases: Vec<ParameterValue> =
            serde_json::from_value(case.get("base_values").cloned().unwrap_or(json!([]))).unwrap();
        for format in [Format::Json, Format::Toml] {
            let text = codec::modulation_text(&definition, format).unwrap();
            assert_eq!(codec::parse_modulation(&text, format).unwrap(), definition);
        }
        let reversed = Modulation::new(
            definition.parameters().to_vec(),
            definition.sources().to_vec(),
            definition.routes().iter().rev().cloned().collect(),
        )
        .unwrap();
        for definition in [&definition, &reversed] {
            let result = modulation::evaluate(definition, &values, &bases);
            if case["error"] == "arithmetic-range" {
                assert_eq!(result, Err(Error::ArithmeticRange), "{}", case["id"]);
            } else if !case["error"].is_null() {
                assert!(
                    matches!(result, Err(Error::Invalid(_))),
                    "{}: {result:?}",
                    case["id"]
                );
            } else {
                same(
                    &serde_json::to_value(result.unwrap()).unwrap(),
                    &case["expected"],
                    case["exact_result"] == true,
                );
            }
        }
    }
}
#[test]
fn shared_unicode_and_quantities() {
    let data = data();
    for case in data["identifiers"].as_array().unwrap() {
        let result = Identifier::new(case["value"].as_str().unwrap().into());
        assert_eq!(result.is_ok(), case["valid"] == true, "{}", case["value"]);
    }
    for case in data["quantities"].as_array().unwrap() {
        let result = quantity::scalar(
            case["text"].as_str().unwrap(),
            case["unit"].as_str().unwrap(),
        );
        if case["rejected"] == true {
            assert!(result.is_err(), "{case}");
        } else {
            let (actual, expected) = (result.unwrap(), case["expected"].as_f64().unwrap());
            if expected.abs() > 0.0 && expected.abs() < 1e-12 {
                assert!((actual - expected).abs() <= expected.abs() * 1e-12);
            } else {
                same(&json!(actual), &case["expected"], false);
            }
            if case["negative_zero"] == true {
                assert!(actual.is_sign_negative());
            }
        }
    }
}

#[test]
fn generated_unicode_tables_match_the_packaged_resource_at_boundaries() {
    let resource: Value =
        serde_json::from_str(include_str!("../../../ufor/identifier_ranges.json")).unwrap();
    assert_eq!(resource["unicode_version"], data()["unicode_version"]);
    let lowercase = resource["lowercase"].as_array().unwrap();
    let digits = resource["digits"].as_array().unwrap();
    let contains = |ranges: &[Value], point: u32| {
        ranges.iter().any(|r| {
            r[0].as_u64().unwrap() <= u64::from(point) && u64::from(point) <= r[1].as_u64().unwrap()
        })
    };
    for range in lowercase.iter().chain(digits) {
        let start = range[0].as_u64().unwrap() as u32;
        let end = range[1].as_u64().unwrap() as u32;
        for point in [start - 1, start, end, end + 1] {
            if let Some(character) = char::from_u32(point) {
                assert_eq!(
                    Identifier::new(character.to_string()).is_ok(),
                    contains(lowercase, point)
                );
                assert_eq!(
                    Identifier::new(format!("a{character}")).is_ok(),
                    contains(lowercase, point)
                        || contains(digits, point)
                        || matches!(character, '-' | '_')
                );
            }
        }
    }
}
#[test]
fn shared_local_bindings_report_unresolved_references() {
    for case in data()["local_bindings"].as_array().unwrap() {
        let definition: Modulation = serde_json::from_value(case["input"].clone()).unwrap();
        let bindings: Vec<Binding> = serde_json::from_value(case["bindings"].clone()).unwrap();
        let controls: BTreeMap<Identifier, ControlDeclaration> =
            serde_json::from_value(case["controls"].clone()).unwrap();
        let result = processing::validate_local_bindings(&definition, &bindings, &controls);
        if !case["error"].is_null() {
            assert!(result.is_err(), "{}", case["id"]);
        } else {
            same(
                &serde_json::to_value(result.unwrap()).unwrap(),
                &case["unresolved"],
                false,
            );
        }
    }
}
#[test]
fn shared_preparation_budgets() {
    for case in data()["budgets"].as_array().unwrap() {
        let count = case["count"].as_u64().unwrap() as usize;
        let result = prepare(case["kind"].as_str().unwrap(), count);
        assert_eq!(result.is_err(), case["rejected"] == true, "{case}");
    }
}
fn prepare(kind: &str, count: usize) -> Result<(), String> {
    let parameter = |i| json!({"target":{"name":format!("p{i}"),"parameter":"x"},"unit":"ratio","scope":"voice","minimum":0,"maximum":1,"default":0});
    let source = |i| json!({"name":format!("s{i}"),"scope":"voice","minimum":0,"maximum":1});
    match kind {
        "parameters" => {
            let values: Vec<_> = (0..count).map(parameter).collect();
            serde_json::from_value::<Modulation>(json!({"parameters":values}))
                .map(|_| ())
                .map_err(|e| e.to_string())
        }
        "points" => {
            let points: Vec<_> = (0..count).map(|i| json!({"input":i,"amount":0})).collect();
            serde_json::from_value::<Route>(json!({"name":"r","source":"x","target":{"name":"a","parameter":"x"},"unit":"ratio","operation":"add","points":points})).map(|_| ()).map_err(|e| e.to_string())
        }
        "aggregate" => {
            let parameters: Vec<_> = (0..count).map(parameter).collect();
            let sources: Vec<_> = (0..count).map(source).collect();
            serde_json::from_value::<Modulation>(json!({"parameters":parameters,"sources":sources}))
                .map(|_| ())
                .map_err(|e| e.to_string())
        }
        "bindings" => {
            let sources: Vec<_> = (0..count).map(source).collect();
            let definition: Modulation =
                serde_json::from_value(json!({"sources":sources})).unwrap();
            let bindings = (0..count)
                .map(|i| {
                    serde_json::from_value::<Binding>(
                        json!({"name":format!("s{i}"),"kind":"velocity"}),
                    )
                    .unwrap()
                })
                .collect::<Vec<_>>();
            processing::validate_local_bindings(&definition, &bindings, &BTreeMap::new())
                .map(|v| assert!(v.is_empty()))
                .map_err(|e| e.to_string())
        }
        "identifier" => Identifier::new("a".repeat(count))
            .map(|_| ())
            .map_err(|e| e.to_string()),
        "identifier_unicode" => Identifier::new("é".repeat(count))
            .map(|_| ())
            .map_err(|e| e.to_string()),
        "quantity" => quantity::scalar(&format!("1{}", " ".repeat(count - 1)), "ratio")
            .map(|_| ())
            .map_err(|e| e.to_string()),
        _ => panic!("unknown budget {kind}"),
    }
}
#[test]
fn constructors_preserve_validation_and_reconstruction() {
    use ufor::control::Scope;
    use ufor::modulation::Unit;
    let target = Target::new(
        Identifier::new("a".into()).unwrap(),
        Identifier::new("x".into()).unwrap(),
    );
    assert!(Parameter::new(target, Unit::Hz, Scope::Voice, 0.0, 1.0, 0.0).is_err());
    let point = Point::new(0.0, 1.0).unwrap();
    assert!(Point::new(f64::NAN, 0.0).is_err());
    assert_eq!(point.amount(), 1.0);
    assert!(SourceValue::new(0.0, f64::INFINITY).is_err());
    assert!(ControlDeclaration::new(ufor::control::Polarity::Unipolar, -1.0).is_err());
}
