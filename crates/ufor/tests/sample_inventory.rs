use serde_json::{Value, json};
use std::collections::BTreeMap;
use ufor::codec::{Format, parse_sample_inventory, parse_sample_score_inventory};
use ufor::envelfo::PreparationLimits;

const INVENTORY: &str = r#"{
    "timebases": [
        {"name":"output","kind":"physical","rate":{"numerator":48000}},
        {"name":"native","rate":{"numerator":44100}},
        {"name":"unused","rate":{"numerator":96000,"denominator":2}}
    ],
    "assets": [
        {"name":"clip","audio":{"timebase":"native","channels":["left","right"],"frames":12}},
        {"name":"unused","audio":{"timebase":"unused","channels":["mono"],"frames":4}}
    ],
    "slices": [
        {"name":"start","asset":"clip","end_frame":4},
        {"name":"tail","asset":"clip","start_frame":4,"end_frame":12}
    ],
    "output": {"timebase":"output","channels":["left","right"]}
}"#;

#[test]
fn playback_resolves_only_referenced_assets_at_their_native_rates() {
    let limits = PreparationLimits::new(8).unwrap();
    let inventory = parse_sample_inventory(INVENTORY, Format::Json, limits).unwrap();
    let decoded = BTreeMap::from([("clip".into(), vec![12, 2])]);
    let expected = (48000, BTreeMap::from([("clip".into(), 44100)]));
    assert_eq!(inventory.integer_rates(&decoded).unwrap(), expected);
    let value: Value = serde_json::from_str(INVENTORY).unwrap();
    let toml = toml::to_string(&value).unwrap();
    let restored = parse_sample_inventory(&toml, Format::Toml, limits).unwrap();
    assert_eq!(restored.integer_rates(&decoded).unwrap(), expected);
    assert!(inventory.integer_rates(&BTreeMap::new()).is_err());
    assert!(
        inventory
            .integer_rates(&BTreeMap::from([("clip".into(), vec![12])]))
            .is_err()
    );
    assert!(
        inventory
            .integer_rates(&BTreeMap::from([
                ("clip".into(), vec![12, 2]),
                ("unused".into(), vec![4, 1]),
            ]))
            .is_err()
    );
    assert!(
        parse_sample_inventory(INVENTORY, Format::Json, PreparationLimits::new(7).unwrap())
            .is_err()
    );
}

#[test]
fn inventory_checks_timebases_slice_extents_and_channel_names() {
    let original: Value = serde_json::from_str(INVENTORY).unwrap();
    for (field, invalid) in [
        ("/assets/0/audio/timebase", json!("missing")),
        ("/timebases/1/name", json!("output")),
        ("/timebases/1/rate/numerator", json!(0)),
        ("/slices/1/end_frame", json!(13)),
        ("/slices/1/asset", json!("missing")),
        ("/assets/0/audio/channels", json!(["left", "left"])),
        ("/output/channels", json!([""])),
    ] {
        let mut document = original.clone();
        *document.pointer_mut(field).unwrap() = invalid;
        assert!(
            parse_sample_inventory(
                &document.to_string(),
                Format::Json,
                PreparationLimits::default()
            )
            .is_err(),
            "accepted {field}",
        );
    }

    let mut document = original;
    document["timebases"][1]["rate"] = json!({"numerator":88200,"denominator":2});
    let inventory = parse_sample_inventory(
        &document.to_string(),
        Format::Json,
        PreparationLimits::default(),
    )
    .unwrap();
    assert!(
        inventory
            .integer_rates(&BTreeMap::from([("clip".into(), vec![12, 2])]))
            .is_err()
    );
}

#[test]
fn authored_sampler_score_prepares_the_same_inventory_in_both_formats() {
    let score = sample_score();
    let decoded = BTreeMap::from([("clip".into(), vec![12, 2])]);
    let expected = (48000, BTreeMap::from([("clip".into(), 44100)]));
    for (text, format) in [
        (score.to_string(), Format::Json),
        (toml::to_string(&score).unwrap(), Format::Toml),
    ] {
        let inventory =
            parse_sample_score_inventory(&text, format, PreparationLimits::new(8).unwrap())
                .unwrap();
        assert_eq!(inventory.integer_rates(&decoded).unwrap(), expected);
        assert!(
            parse_sample_score_inventory(&text, format, PreparationLimits::new(7).unwrap())
                .is_err()
        );
    }
}

#[test]
fn authored_sampler_score_checks_finite_sources_and_port_connections() {
    let score = sample_score();
    let limits = PreparationLimits::default();
    for (field, invalid, expected) in [
        (
            "/assets/0/location",
            json!({"kind":"stream","url":"https://example.test/stream","transport":"https"}),
            "finite, seekable",
        ),
        (
            "/assets/1/location/delivery",
            json!("callback"),
            "finite, seekable",
        ),
        (
            "/inputs/0/stream/timebase",
            json!("missing"),
            "unknown timebase",
        ),
        (
            "/inputs/0/stream/kinds/2",
            json!("key"),
            "native performance events",
        ),
        ("/body/slots/0/slice", json!("missing"), "Unknown slice"),
        (
            "/body/slots/0/channels/0/input",
            json!("mono"),
            "Unknown channel",
        ),
        (
            "/body/slots/0/channels/0/output",
            json!("mono"),
            "Unknown channel",
        ),
    ] {
        let mut document = score.clone();
        *document.pointer_mut(field).unwrap() = invalid;
        let err = parse_sample_score_inventory(&document.to_string(), Format::Json, limits)
            .err()
            .unwrap();
        assert!(err.to_string().contains(expected), "{err}");
    }
}

fn sample_score() -> Value {
    let mut inventory: Value = serde_json::from_str(INVENTORY).unwrap();
    inventory["assets"][0]["location"] = json!({"kind":"relative_file","path":"clip.wav"});
    inventory["assets"][1]["location"] =
        json!({"kind":"python_provider","module":"kit","function":"clip","delivery":"buffer"});
    json!({
        "format":"recs",
        "version":4,
        "kind":"instrument",
        "name":"demo",
        "title":"Demo",
        "timebases":inventory["timebases"],
        "assets":inventory["assets"],
        "inputs":[{
            "name":"performance",
            "binding":{"performance":true},
            "stream":{"family":"event","timebase":"output","kinds":["trigger","release","control_change"]}
        }],
        "outputs":[{
            "name":"audio",
            "binding":{"audio":true},
            "stream":inventory["output"]
        }],
        "body":{
            "kind":"sample_instrument",
            "slices":inventory["slices"],
            "slots":[{
                "name":"voice","slice":"start","channels":[{"input":"left","output":"left","gain":1}],
                "mapping":{"reference_pitch_hz":440}
            }]
        }
    })
}
