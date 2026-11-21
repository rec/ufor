use serde_json::{Value, json};
use ufor::codec::{self, Format};
use ufor::effects::topology::Topology;
use ufor::envelfo::PreparationLimits;

#[test]
fn follower_dependency_and_latency_match_shared_effect_cases() {
    let data: Value =
        serde_json::from_str(include_str!("../../../conformance/follower.json")).unwrap();
    let graph = projection(data["graph"].clone());
    let limits = PreparationLimits::default();
    for (text, format) in [
        (graph.to_string(), Format::Json),
        (toml::to_string(&graph).unwrap(), Format::Toml),
    ] {
        let topology = codec::parse_effect_topology(&text, format, limits).unwrap();
        assert_eq!(json!(topology.order()), data["order"]);
        assert_eq!(json!(topology.output_channels()), data["channels"]);
        assert_eq!(json!(topology.latencies(48000).unwrap()), data["latencies"]);
        assert_eq!(
            json!(topology.layouts()),
            json!({"detector_shape": ["left", "right"], "level": ["level"], "output": ["left", "right"]})
        );
    }

    let mut cycle = graph.clone();
    cycle["connections"][1]["source"] = json!({"kind": "processor", "processor": "output"});
    assert!(
        Topology::decode(cycle, limits)
            .unwrap_err()
            .to_string()
            .contains("cycle")
    );
    let mut audio_follower = graph.clone();
    audio_follower["connections"][0]["source"] = json!({"kind": "processor", "processor": "level"});
    assert!(Topology::decode(audio_follower, limits).is_err());
    let mut detached = graph;
    detached["bindings"] = json!([]);
    detached["modulation"] = json!({});
    assert!(Topology::decode(detached, limits).is_err());
}

#[test]
fn mixer_layout_and_convolution_latency_match_shared_effect_cases() {
    let mix: Value = serde_json::from_str(include_str!("../../../conformance/mixer.json")).unwrap();
    let limits = PreparationLimits::default();
    let mut graph = projection(mix["graph"].clone());
    let topology = Topology::decode(graph.clone(), limits).unwrap();
    assert_eq!(json!(topology.output_channels()), json!(["left", "right"]));
    graph["inputs"][1]["channels"] = json!(["right", "left"]);
    assert!(Topology::decode(graph, limits).is_err());

    let convolution: Value =
        serde_json::from_str(include_str!("../../../conformance/convolution.json")).unwrap();
    let topology = Topology::decode(projection(convolution.clone()), limits).unwrap();
    assert_eq!(
        json!(topology.latencies(48000).unwrap()),
        json!({"room": convolution["processors"][0]["partition_frames"]})
    );
}

#[test]
fn effect_action_batches_match_the_shared_authored_contract() {
    let data: Value =
        serde_json::from_str(include_str!("../../../conformance/effects.json")).unwrap();
    let topology = Topology::decode(
        projection(data["graph"].clone()),
        PreparationLimits::default(),
    )
    .unwrap();
    let batch = codec::parse_effect_action_batch(&data["batch"].to_string(), Format::Json).unwrap();
    topology.validate_batch(&batch, 2).unwrap();
    assert!(!batch.lifecycle());
    assert_eq!(batch.actions()[0].tick(), 1024);
    assert!(topology.validate_batch(&batch, 1).is_err());
    let batch_text = toml::to_string(&batch).unwrap();
    let round_trip = codec::parse_effect_action_batch(&batch_text, Format::Toml).unwrap();
    assert_eq!(round_trip, batch);

    let mut invalid_batch = data["batch"].clone();
    invalid_batch["actions"][1]["ordinal"] = json!(7);
    assert!(codec::parse_effect_action_batch(&invalid_batch.to_string(), Format::Json).is_err());

    let release = codec::parse_effect_action(
        r#"{"kind":"input_end","input":"main","tick":1024,"ordinal":7}"#,
        Format::Json,
    )
    .unwrap();
    assert!(release.lifecycle());
    topology.validate_action(&release).unwrap();

    let invalid = codec::parse_effect_action(
        r#"{"kind":"freeze","processor":"ring","tick":0,"ordinal":0,"frozen":true}"#,
        Format::Json,
    )
    .unwrap();
    assert!(topology.validate_action(&invalid).is_err());
}

#[test]
fn mixer_selectors_and_bitcrusher_actions_require_immediate_requests() {
    let mix: Value = serde_json::from_str(include_str!("../../../conformance/mixer.json")).unwrap();
    let limits = PreparationLimits::default();
    let mixer = Topology::decode(projection(mix["graph"].clone()), limits).unwrap();
    let mut graph = projection(mix["graph"].clone());
    graph["processors"] = json!([{"name":"sum","kind":"bitcrusher"}]);
    graph["connections"] = json!([
        {"processor":"sum","port":"input","source":{"kind":"input","input":"main"}}
    ]);
    let bitcrusher = Topology::decode(graph, limits).unwrap();
    for (topology, parameter, value) in [(&mixer, "a-muted", 1), (&bitcrusher, "bits", 12)] {
        let mut action = json!({
            "kind":"parameter","processor":"sum","parameter":parameter,
            "tick":0,"ordinal":0,"value":value
        });
        topology
            .validate_action(
                &codec::parse_effect_action(&action.to_string(), Format::Json).unwrap(),
            )
            .unwrap();
        action["duration_frames"] = json!(1);
        assert!(
            topology
                .validate_action(
                    &codec::parse_effect_action(&action.to_string(), Format::Json).unwrap()
                )
                .is_err()
        );
    }
}

fn projection(mut graph: Value) -> Value {
    graph.as_object_mut().unwrap().retain(|key, _| {
        [
            "scope",
            "owner",
            "inputs",
            "processors",
            "connections",
            "output",
            "modulation",
            "bindings",
        ]
        .contains(&key.as_str())
    });
    graph
}
