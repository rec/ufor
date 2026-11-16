use serde::Serialize;
use serde_json::Value;
use ufor::codec::{self, Format};
use ufor::error::Error;
use ufor::musical::TuningScore;
use ufor::number::Number;
use ufor::tuning::{Computed, FrequencyTable, IntervalPattern, RatioTable, Source, Tuning};

#[derive(Debug, Serialize)]
#[serde(untagged)]
enum Definition {
    Source(Source),
    Tuning(Tuning),
    Score(TuningScore),
}

impl Definition {
    fn parse(model: &str, value: Value) -> Result<Self, serde_json::Error> {
        match model {
            "computed" => serde_json::from_value(value).map(|v| Self::Source(Source::Computed(v))),
            "ratios" => serde_json::from_value(value).map(|v| Self::Source(Source::Ratios(v))),
            "intervals" => {
                serde_json::from_value(value).map(|v| Self::Source(Source::Intervals(v)))
            }
            "frequencies" => {
                serde_json::from_value(value).map(|v| Self::Source(Source::Frequencies(v)))
            }
            "tuning" => serde_json::from_value(value).map(Self::Tuning),
            "score" => serde_json::from_value(value).map(Self::Score),
            model => panic!("unknown model {model}"),
        }
    }

    fn evaluate(&self, note: i64) -> Result<Number, Error> {
        match self {
            Self::Source(value) => value.evaluate(note),
            Self::Tuning(value) => value.evaluate(note),
            Self::Score(value) => value.body().evaluate(note),
        }
    }
}

fn data() -> Value {
    serde_json::from_str(include_str!("../../../conformance/tuning.json")).unwrap()
}

#[test]
fn definitions_match_shared_cases_and_roundtrip_both_formats() {
    let data = data();
    for case in data["valid"].as_array().unwrap() {
        let model = case["model"].as_str().unwrap();
        let definition = Definition::parse(model, case["input"].clone())
            .unwrap_or_else(|e| panic!("{}: {e}", case["id"]));
        let normalized = serde_json::to_value(&definition).unwrap();
        if !case["normalized"].is_null() {
            assert_eq!(normalized, case["normalized"], "{}", case["id"]);
        }
        for format in [Format::Json, Format::Toml] {
            let roundtrip = match &definition {
                Definition::Tuning(value) => serde_json::to_value(
                    codec::parse_tuning(&codec::tuning_text(value, format).unwrap(), format)
                        .unwrap(),
                )
                .unwrap(),
                Definition::Score(value) => serde_json::to_value(
                    codec::parse_score(
                        &codec::score_text(&ufor::score::Score::Tuning(value.clone()), format)
                            .unwrap(),
                        format,
                        ufor::envelfo::PreparationLimits::default(),
                    )
                    .unwrap(),
                )
                .unwrap(),
                Definition::Source(_) => {
                    let wire = match format {
                        Format::Json => normalized.clone(),
                        Format::Toml => {
                            let text = toml::to_string(&definition).unwrap();
                            serde_json::to_value(toml::from_str::<toml::Value>(&text).unwrap())
                                .unwrap()
                        }
                    };
                    serde_json::to_value(Definition::parse(model, wire).unwrap()).unwrap()
                }
            };
            assert_eq!(roundtrip, normalized, "{} {format:?}", case["id"]);
        }
        if let Some(lookups) = case["lookups"].as_array() {
            for lookup in lookups {
                let note = lookup["note"].as_str().unwrap().parse().unwrap();
                let actual = definition.evaluate(note);
                if lookup["outside"] == true {
                    assert_eq!(actual, Err(Error::OutsideDomain), "{}: {note}", case["id"]);
                } else {
                    let actual = actual.unwrap_or_else(|e| panic!("{}: {note}: {e}", case["id"]));
                    if let Some(exact) = lookup["exact"].as_str() {
                        assert!(actual.rational().is_some(), "{}", case["id"]);
                        assert_eq!(actual.to_string(), exact, "{}: {note}", case["id"]);
                    } else {
                        assert!(actual.rational().is_none(), "{}", case["id"]);
                        let expected = lookup["approx"].as_f64().unwrap();
                        assert!(
                            (actual.as_f64() - expected).abs()
                                <= 1e-12_f64.max(expected.abs() * 1e-12),
                            "{}: {note}",
                            case["id"]
                        );
                    }
                }
            }
        }
        if !case["as_ratios"].is_null() {
            let Definition::Source(Source::Computed(value)) = definition else {
                panic!("expected computed")
            };
            assert_eq!(
                serde_json::to_value(value.as_ratios().unwrap()).unwrap(),
                case["as_ratios"]
            );
        }
    }
}

#[test]
fn invalid_definitions_and_portable_types_are_rejected() {
    let data = data();
    for case in data["invalid"]
        .as_array()
        .unwrap()
        .iter()
        .chain(data["approved_contract"]["invalid"].as_array().unwrap())
    {
        assert!(
            Definition::parse(case["model"].as_str().unwrap(), case["input"].clone()).is_err(),
            "{}",
            case["id"]
        );
    }
}

#[test]
fn evaluation_failures_have_explicit_categories() {
    let data = data();
    for case in data["approved_contract"]["evaluation_errors"]
        .as_array()
        .unwrap()
    {
        let definition =
            Definition::parse(case["model"].as_str().unwrap(), case["input"].clone()).unwrap();
        for lookup in case["lookups"].as_array().unwrap() {
            let expected = match lookup["error"].as_str().unwrap() {
                "arithmetic-range" => Error::ArithmeticRange,
                "nonpositive-result" => Error::NonpositiveResult,
                error => panic!("unknown error {error}"),
            };
            assert_eq!(
                definition.evaluate(lookup["note"].as_str().unwrap().parse().unwrap()),
                Err(expected),
                "{}",
                case["id"]
            );
        }
    }
}

#[test]
fn direct_construction_and_reconstruction_preserve_invariants() {
    assert!(Computed::new(0, "2".into(), 0).is_err());
    assert!(FrequencyTable::new(vec!["0".into()], 0).is_err());
    assert!(IntervalPattern::new(vec![], true).is_err());
    let original = RatioTable::new(vec!["5/4".into()], None, "just".into(), "test".into()).unwrap();
    let mut values = original.values().to_vec();
    values[0] = "3/2".into();
    let edited = RatioTable::new(
        values.clone(),
        None,
        original.name().into(),
        original.description().into(),
    )
    .unwrap();
    assert_eq!(original.evaluate(0).unwrap().to_string(), "5/4");
    assert_eq!(edited.evaluate(0).unwrap().to_string(), "3/2");
    values[0] = "0".into();
    assert!(RatioTable::new(values, None, String::new(), String::new()).is_err());
    assert!(
        Tuning::new(
            Source::Computed(Computed::default()),
            0,
            "440".into(),
            f64::NAN
        )
        .is_err()
    );
    assert!(
        TuningScore::new(
            "bad/name".into(),
            "title".into(),
            vec![],
            serde_json::from_value(serde_json::json!({"source":{"kind":"computed"}})).unwrap()
        )
        .is_err()
    );
}

#[test]
fn preparation_limits_cover_tables_and_materialization() {
    let data = data();
    for case in data["approved_contract"]["preparation_budgets"]
        .as_array()
        .unwrap()
    {
        let count = case["count"].as_u64().unwrap() as usize;
        let model = case["model"].as_str().unwrap();
        let result = if model == "computed" {
            Computed::new(count as i64, "1".into(), 0)
                .unwrap()
                .as_ratios()
                .map(|v| assert_eq!(v.values().len(), count))
                .map_err(|e| e.to_string())
        } else {
            let field = if model == "intervals" {
                "intervals"
            } else {
                "values"
            };
            Definition::parse(model, serde_json::json!({field: vec!["1"; count]}))
                .map(|_| ())
                .map_err(|e| e.to_string())
        };
        assert_eq!(
            result.is_err(),
            case["rejected"].as_bool().unwrap(),
            "{}",
            case["id"]
        );
    }
    let large = Computed::new(i64::MAX, "2".into(), 0).unwrap();
    assert_eq!(large.evaluate(0).unwrap().to_string(), "1");
    assert!(matches!(large.as_ratios(), Err(Error::Limit(_))));
}
