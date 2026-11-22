use ufor::codec::{Format, parse_sample_slice};
use ufor::samples::cursor::Cursor;
use ufor::samples::playback::Playback;

const RATE: f64 = 48000.0;

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
    assert_eq!(cursor.state().index, 7);
    assert_eq!(cursor.state().position, RATE / 2.0);
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
