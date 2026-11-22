use serde_json::{Value, json};
use ufor::codec::{Format, parse_scale, parse_score, scale_text, score_text};
use ufor::envelfo::PreparationLimits;
use ufor::error::Error;
use ufor::score::Score;

const CASES: &str = include_str!("../../../conformance/scale.json");

#[test]
fn shared_scales_preserve_names_and_tuning_coordinates() {
    let vectors: Value = serde_json::from_str(CASES).unwrap();
    for case in vectors["valid"].as_array().unwrap() {
        let scale = parse_scale(&case["input"].to_string(), Format::Json).unwrap();
        assert_eq!(json!(scale.names()), case["names"]);
        assert_eq!(json!(scale.octave_length()), case["octave_length"]);
        assert_eq!(json!(scale.note_count()), case["note_count"]);
        for format in [Format::Json, Format::Toml] {
            let text = scale_text(&scale, format).unwrap();
            assert_eq!(parse_scale(&text, format).unwrap(), scale);
        }
        for lookup in case["lookups"].as_array().unwrap() {
            let number = lookup["number"].as_i64().unwrap();
            assert_eq!(json!(scale.to_name(number, true).unwrap()), lookup["sharp"]);
            assert_eq!(json!(scale.to_name(number, false).unwrap()), lookup["flat"]);
            assert_eq!(
                json!(scale.tuning_number(number).unwrap()),
                lookup["tuning"]
            );
            for name in ["sharp", "flat", "alias"] {
                if let Some(spelling) = lookup[name].as_str() {
                    assert_eq!(scale.to_number(spelling).unwrap(), number);
                }
            }
        }
    }
    for input in vectors["invalid"].as_array().unwrap() {
        assert!(
            parse_scale(&input.to_string(), Format::Json).is_err(),
            "{input}"
        );
    }
}

#[test]
fn scale_scores_round_trip_and_keep_checked_coordinates() {
    let text = json!({
        "kind":"scale", "name":"scale", "title":"One note",
        "tags":["#music","#music"], "body":{"notes":"C","offset":i64::MAX},
    })
    .to_string();
    let limits = PreparationLimits::default();
    let score = parse_score(&text, Format::Json, limits).unwrap();
    let Score::Scale(scale) = &score else {
        panic!("expected scale score");
    };
    assert_eq!(scale.tags(), ["#music"]);
    assert_eq!(
        scale
            .body()
            .to_number(&scale.body().to_name(i64::MIN, true).unwrap())
            .unwrap(),
        i64::MIN
    );
    assert_eq!(
        scale.body().tuning_number(i64::MIN),
        Err(Error::ArithmeticRange)
    );
    let text = score_text(&score, Format::Toml).unwrap();
    assert_eq!(parse_score(&text, Format::Toml, limits).unwrap(), score);

    let empty = parse_scale(r#"{"intervals":[0]}"#, Format::Json).unwrap();
    assert!(empty.to_name(0, true).is_err());
    assert!(empty.tuning_number(0).is_err());
    assert!(empty.to_number("C0").is_err());
    let normal = parse_scale("{}", Format::Json).unwrap();
    assert_eq!(
        normal.frequency(|_| Err(Error::OutsideDomain), 60),
        Err(Error::OutsideDomain)
    );
}
