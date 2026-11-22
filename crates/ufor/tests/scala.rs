use serde_json::Value;
use ufor::error::Error;
use ufor::scala::{parse_scala, scala_text};
use ufor::tuning::{MAX_TABLE_ENTRIES, RatioTable};

const CASES: &str = include_str!("../../../conformance/scala.json");

#[test]
fn shared_scala_cases_preserve_authored_ratios_and_cents() {
    let vectors: Value = serde_json::from_str(CASES).unwrap();
    for case in vectors["valid"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let table = parse_scala(case["source"].as_str().unwrap(), name).unwrap();
        assert_eq!(table.name(), name);
        assert_eq!(table.description(), case["description"].as_str().unwrap());
        assert_eq!(
            serde_json::to_value(table.ratios()).unwrap(),
            case["ratios"]
        );
        assert_eq!(table.repeat_ratio(), case["repeat_ratio"].as_str());
        let text = scala_text(&table).unwrap();
        assert_eq!(text, case["exported"].as_str().unwrap());
        let restored = parse_scala(&text, name).unwrap();
        for lookup in case["lookups"].as_array().unwrap() {
            let degree = lookup["degree"].as_i64().unwrap();
            for table in [&table, &restored] {
                let pitch = table.evaluate(degree).unwrap();
                if let Some(expected) = lookup["exact"].as_str() {
                    assert_eq!(pitch.rational().unwrap().to_string(), expected);
                } else {
                    assert!((pitch.as_f64() - lookup["approx"].as_f64().unwrap()).abs() < 1e-14);
                }
            }
        }
    }
}

#[test]
fn shared_invalid_scala_text_and_exports_fail() {
    let vectors: Value = serde_json::from_str(CASES).unwrap();
    for case in vectors["invalid_text"].as_array().unwrap() {
        assert!(parse_scala(case.as_str().unwrap(), "").is_err(), "{case}");
    }
    for case in vectors["invalid_export"].as_array().unwrap() {
        let table: RatioTable = serde_json::from_value(case.clone()).unwrap();
        assert!(scala_text(&table).is_err(), "{case}");
    }
    assert!(matches!(
        parse_scala(&format!("Oversized\n{}\n2\n", MAX_TABLE_ENTRIES + 1), ""),
        Err(Error::Limit("tuning table entries"))
    ));
}
