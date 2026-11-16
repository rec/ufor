use ufor::codec::{self, Format};
use ufor::envelfo::PreparationLimits;
use ufor::error::Error;
use ufor::musical::TuningScore;
use ufor::score::Score;

#[test]
fn shared_python_document_roundtrips_json_and_toml() {
    let source = include_str!("../../../conformance/library/scores/tuning.toml");
    let score = codec::parse_score(source, Format::Toml, PreparationLimits::default()).unwrap();
    assert_eq!(score.name(), "western");
    let Score::Tuning(tuning) = &score else {
        panic!("expected tuning");
    };
    assert_eq!(tuning.body().evaluate(69).unwrap().to_string(), "440");
    for format in [Format::Json, Format::Toml] {
        let text = codec::score_text(&score, format).unwrap();
        assert_eq!(
            codec::parse_score(&text, format, PreparationLimits::default()).unwrap(),
            score
        );
    }
}

#[test]
fn headers_and_unknown_fields_use_the_same_validated_boundary() {
    let valid = serde_json::json!({"kind":"tuning", "name":"a", "title":"A", "body":{"source":{"kind":"computed"}}});
    for (key, value) in [
        ("name", serde_json::json!(" a")),
        ("name", serde_json::json!("a.*")),
        ("format", serde_json::json!("ufor")),
        ("kind", serde_json::json!("scale")),
        ("extra", serde_json::json!(1)),
        ("tags", serde_json::json!(["#ok", "#bad tag"])),
    ] {
        let mut input = valid.clone();
        input[key] = value;
        assert!(
            serde_json::from_value::<TuningScore>(input.clone()).is_err(),
            "{input}"
        );
        assert!(
            codec::parse_score(
                &input.to_string(),
                Format::Json,
                PreparationLimits::default()
            )
            .is_err(),
            "{input}"
        );
    }
    let mut no_kind = valid;
    no_kind.as_object_mut().unwrap().remove("kind");
    assert!(serde_json::from_value::<TuningScore>(no_kind.clone()).is_ok());
    assert!(
        codec::parse_score(
            &no_kind.to_string(),
            Format::Json,
            PreparationLimits::default()
        )
        .is_err()
    );
    assert!(
        codec::parse_score(
            "version = 4.0\nkind='tuning'\nname='a'\ntitle='A'\n[body.source]\nkind='computed'",
            Format::Toml,
            PreparationLimits::default()
        )
        .is_err()
    );
    assert!(
        codec::parse_tuning(
            "[source]\nkind='computed'\nnotes_per_octave=12.0",
            Format::Toml
        )
        .is_err()
    );
    assert!(
        codec::parse_tuning("detune_cents=nan\n[source]\nkind='computed'", Format::Toml).is_err()
    );
}

#[test]
fn document_limits_reject_excessive_preparation_work() {
    let mut nested = "0".to_owned();
    for _ in 0..65 {
        nested = format!("[{nested}]");
    }
    assert!(matches!(
        codec::parse_tuning(&nested, Format::Json),
        Err(Error::Limit("document values or depth"))
    ));
    let text = format!(
        "{{\"source\":{{\"kind\":\"computed\"}},\"extra\":[{}]}}",
        vec!["0"; 100001].join(",")
    );
    assert!(matches!(
        codec::parse_tuning(&text, Format::Json),
        Err(Error::Limit("document values or depth"))
    ));
    assert!(matches!(
        codec::parse_tuning(&" ".repeat(codec::MAX_SCORE_CHARACTERS + 1), Format::Toml),
        Err(Error::Limit("score characters"))
    ));
}
