use serde::Deserialize;
use ufor::codec::{self, Format};
use ufor::envelfo::PreparationLimits;
use ufor::samples::routing::{
    ChannelRoute, PanLaw, SpatialTarget, channel_matrix, pan_gains, sampler_matrix, spatial_bounds,
    validate_sampler_spatial,
};

#[derive(Deserialize)]
struct Vectors {
    pan: Vec<(PanLaw, bool, f64, [f64; 2])>,
    matrices: Vec<MatrixCase>,
}

#[derive(Deserialize)]
struct MatrixCase {
    inputs: Vec<String>,
    outputs: Vec<String>,
    routes: Vec<ChannelRoute>,
    spatial: Option<(PanLaw, f64, f64)>,
    expected: Vec<Vec<f64>>,
}

#[test]
fn pan_and_routes_match_shared_vectors() {
    let vectors: Vectors =
        serde_json::from_str(include_str!("../../../conformance/channel-routing.json")).unwrap();
    for (law, stereo, position, expected) in vectors.pan {
        let actual = pan_gains(position, law, stereo).unwrap();
        for (value, wanted) in actual.into_iter().zip(expected) {
            assert!((value - wanted).abs() <= 1e-14);
        }
    }
    for spec in vectors.matrices {
        let matrix = if let Some((law, pan, balance)) = spec.spatial {
            sampler_matrix(&spec.inputs, &spec.outputs, &spec.routes, law, pan, balance)
        } else {
            channel_matrix(&spec.inputs, &spec.outputs, &spec.routes)
        }
        .unwrap();
        assert_eq!(matrix.len(), spec.expected.len());
        for (row, expected) in matrix.iter().zip(&spec.expected) {
            assert_eq!(row.len(), expected.len());
            for (value, wanted) in row.iter().zip(expected) {
                assert!((value - wanted).abs() <= 1e-14);
            }
        }
    }
    assert!(pan_gains(f64::NAN, PanLaw::Native, false).is_err());
}

#[test]
fn sampler_spatial_bounds_include_activation_and_layering() {
    let vectors: serde_json::Value =
        serde_json::from_str(include_str!("../../../conformance/sampler-spatial.json")).unwrap();
    let instrument = codec::parse_sound_settings(
        &vectors["instrument"].to_string(),
        Format::Json,
        PreparationLimits::default(),
    )
    .unwrap();
    for (name, target) in [
        ("pan", SpatialTarget::Pan),
        ("stereo_balance", SpatialTarget::StereoBalance),
    ] {
        let expected: (f64, f64) = serde_json::from_value(vectors[name].clone()).unwrap();
        assert_eq!(spatial_bounds(&instrument, target).unwrap(), expected);
    }
    for case in vectors["slots"].as_array().unwrap() {
        let slot = codec::parse_sound_settings(
            &serde_json::json!({"processing": case["processing"]}).to_string(),
            Format::Json,
            PreparationLimits::default(),
        )
        .unwrap();
        assert_eq!(
            validate_sampler_spatial(&instrument, &slot).is_ok(),
            case["valid"].as_bool().unwrap(),
        );
    }
}
