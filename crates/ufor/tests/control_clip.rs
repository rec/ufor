use serde::Deserialize;
use ufor::automation::AutomationScore;
use ufor::automation::placement::{ControlClip, OutputSelection};
use ufor::codec::{Format, parse_control_clip, parse_score};
use ufor::envelfo::PreparationLimits;
use ufor::identifier::Identifier;
use ufor::score::Score;
use ufor::time::{Rate, TickRange, Timebase};

const GAIN: &str = include_str!("../../../examples/automation/gain.toml");

#[test]
fn requests_the_shared_control_clip_window() {
    #[derive(Deserialize)]
    struct Case {
        source_rate: i64,
        timeline_rate: i64,
        source_interval: [i64; 2],
        timeline_start: i64,
        requested_timeline: [i64; 2],
        requested_source: [i64; 2],
    }

    let case: Case =
        serde_json::from_str(include_str!("../../../conformance/control-clips.json")).unwrap();
    let score = automation(GAIN);
    assert_eq!(score.timebase().rate().integer_hz(), Some(case.source_rate));
    let timeline = clock(case.timeline_rate, 1);
    let [source_start, source_end] = case.source_interval;
    let definition = format!(
        r#"
        name = "fade"
        source = {{ part = "automation", output = "control" }}
        source_start = {source_start}
        source_end = {source_end}
        timeline_start = {}
        "#,
        case.timeline_start
    );
    let clip = parse_control_clip(&definition, Format::Toml).unwrap();
    let placement = clip.prepare(&score, &timeline).unwrap();
    let window = range(case.requested_timeline);
    assert_eq!(
        placement.source_request(window).unwrap(),
        Some(range(case.requested_source))
    );
    assert_eq!(placement.timeline(), window);
}

#[test]
fn requests_control_history_and_rejects_fractional_endpoints() {
    let score = automation(GAIN);
    let timeline = clock(48000, 1);
    let clip = clip("control", range([-100, 100]), 480);
    let placement = clip.prepare(&score, &timeline).unwrap();
    assert_eq!(placement.timeline(), range([480, 10080]));
    assert_eq!(placement.source_request(range([0, 480])).unwrap(), None);
    assert_eq!(
        placement.source_request(range([10080, 11000])).unwrap(),
        None
    );
    assert_eq!(
        placement.source_request(range([5039, 5280])).unwrap(),
        Some(range([-100, 0]))
    );
    assert!(placement.source_request(range([5039, 5281])).is_err());
    assert_eq!(
        placement.source_request(range([10079, 10081])).unwrap(),
        Some(range([-100, 100]))
    );
    assert!(clip.prepare(&score, &clock(44100, 116)).is_err());
}

#[test]
fn checks_the_resolved_output_profile_and_timeline_extent() {
    let score = automation(GAIN);
    let timeline = clock(1000, 1);
    assert!(
        clip("missing", range([0, 1]), 0)
            .prepare(&score, &timeline)
            .is_err()
    );
    assert!(
        clip("control", range([0, 1]), i64::MAX)
            .prepare(&score, &timeline)
            .is_err()
    );
    let gate = automation(include_str!("../../../examples/automation/gate.toml"));
    assert!(
        clip("control", range([0, 1]), 0)
            .prepare(&gate, &timeline)
            .is_err()
    );
    let voice = automation(&GAIN.replace("\"part\"", "\"voice\""));
    assert!(
        clip("control", range([0, 1]), 0)
            .prepare(&voice, &timeline)
            .is_err()
    );
}

fn automation(source: &str) -> AutomationScore {
    let Score::Automation(score) =
        parse_score(source, Format::Toml, PreparationLimits::default()).unwrap()
    else {
        panic!("expected automation");
    };
    score
}

fn clip(output: &str, interval: TickRange, start: i64) -> ControlClip {
    ControlClip::new(
        identifier("fade"),
        OutputSelection {
            part: identifier("automation"),
            output: identifier(output),
        },
        interval,
        start,
    )
    .unwrap()
}

fn clock(numerator: i64, denominator: i64) -> Timebase {
    Timebase::new(
        identifier("audio"),
        Rate::new(numerator, denominator).unwrap(),
    )
}

fn identifier(text: &str) -> Identifier {
    Identifier::new(text.into()).unwrap()
}

fn range([start, end]: [i64; 2]) -> TickRange {
    TickRange::new(start, end).unwrap()
}
