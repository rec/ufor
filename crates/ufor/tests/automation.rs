use serde::Deserialize;
use ufor::automation::Value;
use ufor::codec::{Format, automation_text, parse_automation, parse_score, score_text};
use ufor::envelfo::PreparationLimits;
use ufor::score::Score;

#[test]
fn evaluates_and_round_trips_shared_automation_scores() {
    #[derive(Deserialize)]
    struct Fixture {
        cases: Vec<Case>,
    }

    #[derive(Deserialize)]
    struct Case {
        example: String,
        tick: i64,
        #[serde(rename = "override")]
        base_override: Option<Value>,
        expected: Value,
    }

    let fixture: Fixture =
        serde_json::from_str(include_str!("../../../conformance/automation.json")).unwrap();
    let limits = PreparationLimits::default();
    for (name, source) in [
        (
            "gain",
            include_str!("../../../examples/automation/gain.toml"),
        ),
        (
            "frequency",
            include_str!("../../../examples/automation/frequency.toml"),
        ),
        (
            "gate",
            include_str!("../../../examples/automation/gate.toml"),
        ),
    ] {
        let score = parse_score(source, Format::Toml, limits).unwrap();
        let Score::Automation(automation) = &score else {
            panic!("expected automation");
        };
        assert_eq!(
            automation.timebase().name(),
            &automation.output().stream.timebase
        );
        for case in fixture.cases.iter().filter(|case| case.example == name) {
            assert_eq!(
                automation
                    .body()
                    .evaluate(case.tick, case.base_override)
                    .unwrap(),
                case.expected,
                "{name} at tick {}",
                case.tick
            );
        }
        for format in [Format::Json, Format::Toml] {
            let encoded = score_text(&score, format).unwrap();
            assert_eq!(parse_score(&encoded, format, limits).unwrap(), score);
            let encoded_body = automation_text(automation.body(), format).unwrap();
            assert_eq!(
                &parse_automation(&encoded_body, format, limits).unwrap(),
                automation.body()
            );
        }
    }
}

#[test]
fn combines_signed_writers_and_resolves_zero_length_segments_at_large_ticks() {
    let body = r#"{
      "target": {"kind":"route", "name":"main", "destination":"output"},
      "scope":"part", "quantity":"gain", "unit":"ratio", "default":0.25,
      "curves":[
        {"name":"offset","unit":"ratio","operation":"add","at":9223372036854775806,"initial":-0.25},
        {"name":"fade","unit":"ratio","at":9223372036854775805,"initial":0,
         "segments":[{"duration":0,"to":1},{"duration":2,"to":2}]},
        {"name":"scale","unit":"ratio","operation":"multiply","at":9223372036854775806,"initial":2}
      ]
    }"#;
    let automation = parse_automation(body, Format::Json, PreparationLimits::default()).unwrap();
    for (tick, expected) in [
        (i64::MAX - 3, 0.25),
        (i64::MAX - 2, 1.0),
        (i64::MAX - 1, 2.5),
        (i64::MAX, 3.5),
    ] {
        assert_eq!(
            automation.evaluate(tick, None).unwrap(),
            Value::Number(expected)
        );
    }
}

#[test]
fn evaluates_equal_power_across_the_signed_tick_range() {
    let body = r#"{
      "target":{"name":"voice","parameter":"gain"},
      "scope":"voice","quantity":"gain","unit":"ratio","default":1,
      "curves":[{"name":"fade","unit":"ratio","interpolation":"equal_power",
        "at":-9223372036854775808,"initial":1,
        "segments":[
          {"duration":9223372036854775807,"to":1},
          {"duration":9223372036854775708,"to":0},
          {"duration":100,"to":5}
        ]
      }]
    }"#;
    let automation = parse_automation(body, Format::Json, PreparationLimits::default()).unwrap();
    assert_eq!(
        automation.evaluate(i64::MAX - 64, None).unwrap(),
        Value::Number(3.0)
    );
    assert_eq!(
        automation.evaluate(i64::MAX, None).unwrap(),
        Value::Number(5.0)
    );
}

#[test]
fn enforces_the_output_contract_and_combined_record_budget() {
    let source = include_str!("../../../examples/automation/gain.toml");
    let limits = PreparationLimits::default();
    for invalid in [
        source.replace("scope = \"part\" }", "scope = \"voice\" }"),
        source.replace("duration = 2000", "duration = -1"),
        source.replace("initial = 0.0", "initial = false"),
        source.replace("control = true", "control = false"),
    ] {
        assert!(parse_score(&invalid, Format::Toml, limits).is_err());
    }
    assert!(parse_score(source, Format::Toml, PreparationLimits::new(5).unwrap()).is_err());
    assert!(parse_score(source, Format::Toml, PreparationLimits::new(6).unwrap()).is_ok());
}
