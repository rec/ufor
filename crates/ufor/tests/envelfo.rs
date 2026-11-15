//! Preparation foundations for the shared generator-definition contract.
use serde_json::{Value, json};
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
