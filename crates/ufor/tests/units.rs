use ufor::units::{cents, frequency};

#[test]
fn approved_aliases_normalize_to_canonical_quantities() {
    for (unit, expected) in [
        ("Hz", "1"),
        ("hertz", "1"),
        ("kHz", "1000"),
        ("kilohertz", "1000"),
        ("mHz", "1/1000"),
        ("millihertz", "1/1000"),
        ("MHz", "1000000"),
        ("megahertz", "1000000"),
    ] {
        assert_eq!(frequency(&format!("1{unit}")).unwrap(), expected);
    }
    for (unit, expected) in [
        ("cent", 1.0),
        ("cents", 1.0),
        ("musical_cent", 1.0),
        ("semitone", 100.0),
        ("octave", 1200.0),
        ("oct", 1200.0),
    ] {
        assert_eq!(cents(&format!("1 {unit}")).unwrap(), expected);
    }
    assert_eq!(frequency("1 kHz / 3").unwrap(), "1000/3");
    assert_eq!(frequency("2^3 kHz").unwrap(), "8000");
    assert_eq!(frequency("(1 kHz) / 3").unwrap(), "1000/3");
    assert_eq!(frequency("(440/3) Hz").unwrap(), "440/3");
    assert_eq!(frequency(" 440/3 ").unwrap(), " 440/3 ");
    assert_eq!(cents("-1 octave / 2").unwrap(), -600.0);
}

#[test]
fn dimensions_and_multiple_unit_factors_are_rejected() {
    for text in [
        "1 second",
        "1 octave",
        "1 / (3 kHz)",
        "1Hz / 1Hz",
        "1Hz^2",
        "1^(1Hz)",
        "1e309 Hz",
        "0Hz",
        "-1Hz",
    ] {
        assert!(frequency(text).is_err(), "{text}");
    }
    for text in ["1Hz", "1 second", "1/cent", "1 cent^2"] {
        assert!(cents(text).is_err(), "{text}");
    }
}
