use ufor::codec::{Format, parse_sample_slice};
use ufor::number::Rational;
use ufor::samples::cursor::{Cursor, split_step};
use ufor::samples::playback::{Direction, Playback};

const RATE: f64 = 48000.0;

#[test]
fn onset_offsets_follow_direction_and_exhaust_outside_the_slice() {
    let slice = parse_sample_slice(
        r#"{"asset":"clip","name":"section","start_frame":3,"end_frame":12}"#,
        Format::Json,
    )
    .unwrap();
    for (direction, expected) in [
        (Direction::Forward, 6),
        (Direction::Backward, 10),
        (Direction::Mirror, 6),
    ] {
        let playback = Playback {
            direction,
            ..Playback::default()
        };
        let mut cursor = Cursor::new(&slice, playback, 12, RATE, 0, 0.0).unwrap();
        let offset = cursor.start_offset(1, 2).unwrap();
        assert!(cursor.offset_start(offset, 0).unwrap());
        assert_eq!(cursor.state().index, expected);
    }
    let mut cursor = Cursor::new(&slice, Playback::default(), 12, RATE, 0, 0.0).unwrap();
    assert!(cursor.start_offset(i64::MAX, 1).is_err());
    assert!(cursor.offset_start(i64::MAX, 0).is_err());
    assert!(!cursor.offset_start(12, 0).unwrap());
    assert_eq!(cursor.state().exhausted, Some(0));
}

#[test]
fn release_split_rounds_each_exact_product_once() {
    let vectors: serde_json::Value =
        serde_json::from_str(include_str!("../../../conformance/sample-playback.json")).unwrap();
    for row in vectors["release_splits"].as_array().unwrap() {
        let fraction = Rational::new(row[1].as_i64().unwrap(), row[2].as_i64().unwrap()).unwrap();
        let split = split_step(row[0].as_f64().unwrap(), fraction).unwrap();
        assert_eq!(split, (row[3].as_f64().unwrap(), row[4].as_f64().unwrap()));
    }
    let half = Rational::new(1, 2).unwrap();
    assert_eq!(split_step(f64::from_bits(1), half).unwrap(), (0.0, 0.0));
    let even = f64::from_bits(2);
    assert_eq!(split_step(f64::from_bits(3), half).unwrap(), (even, even));
    assert_eq!(
        split_step(f64::MAX, half).unwrap(),
        (f64::MAX / 2.0, f64::MAX / 2.0)
    );
    assert!(split_step(1.0, Rational::from(1)).is_err());
}

#[test]
fn release_can_cancel_a_wrap_pending_at_an_exact_boundary() {
    let slice = parse_sample_slice(
        r#"{"asset":"clip","name":"section","end_frame":12,"loop":{"start_frame":3,"end_frame":9}}"#,
        Format::Json,
    )
    .unwrap();
    let start = Cursor::new(&slice, Playback::default(), 12, RATE, 0, 0.0).unwrap();
    let mut pending = start;
    pending.advance(9.0 * RATE, 9).unwrap();
    assert_eq!(pending.state().index, 9);
    let mut restored = start.resume(*pending.state(), 9).unwrap();
    pending.settle(9);
    assert_eq!(pending.state().index, 3);
    restored.release();
    restored.settle(9);
    assert_eq!(restored.state().index, 9);
    assert!(!restored.state().looping);
}

#[test]
fn overlap_taps_are_linear_without_advancing_the_cursor() {
    let slice = parse_sample_slice(
        r#"{"asset":"clip","name":"section","end_frame":12,
        "loop":{"start_frame":3,"end_frame":10,"crossfade_frames":3}}"#,
        Format::Json,
    )
    .unwrap();
    let mut cursor = Cursor::new(&slice, Playback::default(), 12, RATE, 0, 0.0).unwrap();
    cursor.advance(7.5 * RATE, 8).unwrap();
    assert_eq!(cursor.overlap_tap(), Some((3, 0.0)));
    assert_eq!(cursor.following(8).overlap_tap(), Some((4, 0.5)));
    let audio = [0.0, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0];
    let read = cursor.read_plan(8).unwrap();
    // The overlap knots are 64 and (128 + 8) / 2.
    assert_eq!(read.sample(|index| audio[index as usize]), 66.0);
    assert_eq!(cursor.state().index, 7);
    assert_eq!(cursor.state().position, RATE / 2.0);
}

#[test]
fn linear_read_holds_the_final_value_until_the_cursor_exhausts() {
    let slice = parse_sample_slice(
        r#"{"asset":"clip","name":"section","end_frame":2}"#,
        Format::Json,
    )
    .unwrap();
    let mut cursor = Cursor::new(&slice, Playback::default(), 2, RATE, 0, 0.0).unwrap();
    cursor.advance(1.5 * RATE, 1).unwrap();
    let read = cursor.read_plan(1).unwrap();
    assert_eq!(read.sample(|index| [0.0, 0.75][index as usize]), 0.75);
    assert!(cursor.state().exhausted.is_none());
    cursor.advance(0.5 * RATE, 2).unwrap();
    cursor.settle(2);
    assert!(cursor.read_plan(2).is_none());
}

#[test]
fn a_started_end_fade_keeps_its_coordinate_when_pitch_changes() {
    let slice = parse_sample_slice(
        r#"{"asset":"clip","name":"section","end_frame":12}"#,
        Format::Json,
    )
    .unwrap();
    let start = Cursor::new(&slice, Playback::default(), 12, RATE, 0, 4.0 / RATE).unwrap();
    let frame = (1_i64 << 53) + 1;
    let mut cursor = start;
    cursor.advance(8.0 * RATE, frame).unwrap();
    assert_eq!(cursor.end_gain(frame, RATE), 1.0);
    assert_eq!(cursor.state().end_fade_at, Some(frame));
    let mut resumed = start.resume(*cursor.state(), frame).unwrap();
    assert_eq!(resumed.active_prefix(frame + 1, false, RATE / 2.0, 100), 3);
    assert_eq!(resumed.active_prefix(frame + 4, false, RATE / 2.0, 100), 0);
    assert_eq!(resumed.end_gain(frame + 1, RATE / 2.0), 0.75);
    assert_eq!(resumed.end_gain(frame + 4, RATE / 2.0), 0.0);
    assert_eq!(resumed.state().exhausted, Some(frame + 4));
}

#[test]
fn finite_loops_bound_a_batch_and_release_shortens_infinite_loops() {
    let slice = parse_sample_slice(
        r#"{"asset":"clip","name":"section","end_frame":12,
        "loop":{"start_frame":3,"end_frame":9,"repeat_count":2}}"#,
        Format::Json,
    )
    .unwrap();
    let finite = Cursor::new(&slice, Playback::default(), 12, RATE, 0, 0.0).unwrap();
    assert_eq!(finite.active_prefix(0, false, RATE, 100), 23);
    assert_eq!(finite.active_prefix(0, true, RATE, 100), 11);

    let slice = parse_sample_slice(
        r#"{"asset":"clip","name":"section","end_frame":12,
        "loop":{"start_frame":3,"end_frame":9}}"#,
        Format::Json,
    )
    .unwrap();
    let mut unbounded = Cursor::new(&slice, Playback::default(), 12, RATE, 0, 0.0).unwrap();
    assert_eq!(unbounded.active_prefix(0, false, RATE, 100), 100);
    unbounded.advance(9.0 * RATE, 9).unwrap();
    assert_eq!(unbounded.active_prefix(9, true, RATE, 100), 2);
}
