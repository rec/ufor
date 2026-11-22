use ufor::codec::{Format, parse_timebase};
use ufor::identifier::Identifier;
use ufor::number::Rational;
use ufor::time::{PpqnClock, Rate, Timebase, convert_tick, duration_frames};

#[test]
fn frame_durations_preserve_fractional_holds_and_check_range() {
    let seconds = Rational::new(1, 32000).unwrap();
    assert_eq!(
        duration_frames(seconds, 48000).unwrap(),
        Rational::new(3, 2).unwrap()
    );
    assert_eq!(
        duration_frames(Rational::new(i64::MAX, 48000).unwrap(), 48000).unwrap(),
        i64::MAX.into()
    );
    assert!(duration_frames(i64::MAX.into(), 2).is_err());
    assert!(duration_frames((-1).into(), 48000).is_err());
    assert!(duration_frames(0.into(), 0).is_err());
}

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

#[test]
fn ppqn_clock_rounds_absolute_frames_across_ordered_tempo_changes() {
    let mut clock = PpqnClock::new(1000, 1000).unwrap();
    for (tick, next_tempo, frame) in [
        (1, None, 0),
        (3, Some(250_000), 2),
        (3, Some(1_000_000), 2),
        (4, Some(250_000), 2),
        (6, None, 3),
        (8, None, 4),
    ] {
        assert_eq!(clock.advance(tick, next_tempo).unwrap(), frame);
    }
}

#[test]
fn ppqn_clock_keeps_its_state_after_rejected_advances() {
    let mut clock = PpqnClock::new(1, i64::MAX).unwrap();
    assert!(clock.advance(3, Some(100_000)).is_err());
    assert_eq!(clock.advance(1, None).unwrap(), 4_611_686_018_427_387_904);
    assert!(clock.advance(0, None).is_err());
    assert!(clock.advance(1, Some(0x100_0000)).is_err());
    assert_eq!(clock.advance(2, None).unwrap(), i64::MAX);
    assert!(PpqnClock::new(0, 48000).is_err());
    assert!(PpqnClock::new(0x8000, 48000).is_err());
}

fn timebase(name: &str, numerator: i64, denominator: i64) -> Timebase {
    Timebase::new(
        Identifier::new(name.into()).unwrap(),
        Rate::new(numerator, denominator).unwrap(),
    )
}
