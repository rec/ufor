use ufor::codec::{Format, parse_timebase};
use ufor::identifier::Identifier;
use ufor::time::{Rate, Timebase, convert_tick};

#[test]
fn tick_conversion_matches_exact_shared_vectors() {
    let vectors: Vec<(i64, [i64; 2], [i64; 2], i64)> =
        serde_json::from_str(include_str!("../../../conformance/physical-time.json")).unwrap();
    for (tick, [n, d], [other_n, other_d], expected) in vectors {
        let source = timebase("source", n, d);
        let destination = timebase("destination", other_n, other_d);
        assert_eq!(convert_tick(tick, &source, &destination).unwrap(), expected);
    }

    let slow = timebase("slow", 1, i64::MAX);
    let fast = timebase("fast", i64::MAX, 1);
    assert!(convert_tick(i64::MAX, &slow, &fast).is_err());
}

#[test]
fn wire_rate_preserves_the_declared_denominator() {
    let timebase = parse_timebase(
        r#"{"name":"audio","rate":{"numerator":96000,"denominator":2}}"#,
        Format::Json,
    )
    .unwrap();
    assert_eq!(timebase.rate(), Rate::new(96000, 2).unwrap());
    assert_eq!(timebase.rate().integer_hz(), None);
    let text = toml::to_string(&timebase).unwrap();
    assert_eq!(parse_timebase(&text, Format::Toml).unwrap(), timebase);
    assert!(
        parse_timebase(
            r#"{"name":"audio","rate":{"numerator":48000,"denominator":0}}"#,
            Format::Json,
        )
        .is_err()
    );
}

fn timebase(name: &str, numerator: i64, denominator: i64) -> Timebase {
    Timebase::new(
        Identifier::new(name.into()).unwrap(),
        Rate::new(numerator, denominator).unwrap(),
    )
}
