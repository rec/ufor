use serde_json::Value;
use ufor_core::expression::evaluate;

fn check_case(case: &Value) {
    let text = case["text"].as_str().unwrap();
    let actual = evaluate(text).unwrap_or_else(|error| panic!("{text}: {error}"));
    if let Some(exact) = case["exact"].as_str() {
        assert!(actual.rational().is_some(), "{text}: expected exact");
        assert_eq!(actual.to_string(), exact, "{text}");
    } else {
        assert!(actual.rational().is_none(), "{text}: expected approximate");
        let expected = case["approx"].as_f64().unwrap();
        assert!(
            (actual.as_f64() - expected).abs() <= 1e-12_f64.max(expected.abs() * 1e-12),
            "{text}"
        );
    }
}

#[test]
fn shared_expressions_and_approved_targets() {
    let pitch: Value =
        serde_json::from_str(include_str!("../../../conformance/pitch.json")).unwrap();
    let tuning: Value =
        serde_json::from_str(include_str!("../../../conformance/tuning.json")).unwrap();
    for group in [&pitch, &tuning, &tuning["approved_contract"]] {
        for case in group["expressions"].as_array().unwrap() {
            check_case(case);
        }
        for text in group["invalid_expressions"].as_array().unwrap() {
            let text = text.as_str().unwrap();
            assert!(evaluate(text).is_err(), "{text}");
        }
    }
}

#[test]
fn shared_expression_budgets() {
    let tuning: Value =
        serde_json::from_str(include_str!("../../../conformance/tuning.json")).unwrap();
    for case in tuning["expression_budgets"].as_array().unwrap() {
        let text = case["text"].as_str().unwrap();
        let count = case["count"].as_u64().unwrap() as usize;
        let text = match case["operation"].as_str().unwrap() {
            "pad_right" => format!("{text}{}", " ".repeat(count - text.len())),
            "parentheses" => format!("{}{text}{}", "(".repeat(count), ")".repeat(count)),
            "unary_plus" => format!("{}{text}", "+".repeat(count)),
            operation => panic!("unknown operation {operation}"),
        };
        if case["rejected"] == true {
            assert!(evaluate(&text).is_err(), "{}", case["id"]);
        } else {
            check_case(&serde_json::json!({"text": text, "exact": case["exact"]}));
        }
    }
}
