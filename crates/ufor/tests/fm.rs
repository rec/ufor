use serde_json::{Value, json};
use ufor::codec::{self, Format};
use ufor::envelfo::{PreparationLimits, Waveform};
use ufor::identifier::Identifier;
use ufor::modulation::Target;

#[test]
fn fm_graph_targets_and_order_follow_the_authored_definitions() {
    let corpus: Value =
        serde_json::from_str(include_str!("../../../conformance/fm-graph.json")).unwrap();
    let limits = PreparationLimits::default();
    let graph = codec::parse_fm(&corpus["graph"].to_string(), Format::Json, limits).unwrap();
    assert_eq!(json!(graph.order()), corpus["execution_order"]);
    assert_eq!(graph.operators()[0].phase_cycles(), 0.25);
    assert_eq!(graph.operators()[1].waveform(), Waveform::Sine);
    for row in corpus["targets"].as_array().unwrap() {
        let target = Target::new(
            Identifier::new(row[0].as_str().unwrap().into()).unwrap(),
            Identifier::new(row[1].as_str().unwrap().into()).unwrap(),
        );
        let facts = graph.resolve_target(&target).unwrap();
        assert_eq!(json!(facts.unit), row[2]);
        assert_eq!(facts.default_value, row[3].as_f64().unwrap());
        assert_eq!(json!(facts.minimum), row[4]);
    }
    for raw in corpus["rejected"].as_array().unwrap() {
        assert!(
            codec::parse_fm(&raw.to_string(), Format::Json, limits).is_err(),
            "{raw}"
        );
    }
    for format in [Format::Json, Format::Toml] {
        let text = codec::fm_text(&graph, format).unwrap();
        assert_eq!(codec::parse_fm(&text, format, limits).unwrap(), graph);
    }
    // Root, four operators, three edges, and one explicit Envelope with two segments.
    let text = corpus["graph"].to_string();
    assert!(codec::parse_fm(&text, Format::Json, PreparationLimits::new(11).unwrap()).is_ok());
    assert!(codec::parse_fm(&text, Format::Json, PreparationLimits::new(10).unwrap()).is_err());
}
