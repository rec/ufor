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
