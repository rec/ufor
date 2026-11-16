use ufor::error::Error;
use ufor::expression::evaluate;
use ufor::number::{Number, Rational};

#[test]
fn rational_ordering_keeps_signed_boundaries_and_nearby_fractions_exact() {
    let values = [
        Rational::new(i64::MIN, 1).unwrap(),
        Rational::new(i64::MIN, i64::MAX).unwrap(),
        Rational::new(-1, 1).unwrap(),
        Rational::new(-1, i64::MAX).unwrap(),
        Rational::new(0, 1).unwrap(),
        Rational::new(1, i64::MAX).unwrap(),
        Rational::new(i64::MAX - 2, i64::MAX - 1).unwrap(),
        Rational::new(i64::MAX - 1, i64::MAX).unwrap(),
        Rational::new(1, 1).unwrap(),
        Rational::new(i64::MAX, 1).unwrap(),
    ];
    for pair in values.windows(2) {
        assert!(pair[0] < pair[1]);
        assert!(pair[1] > pair[0]);
    }
    assert_eq!(
        Rational::new(2, 4)
            .unwrap()
            .cmp(&Rational::new(1, 2).unwrap()),
        std::cmp::Ordering::Equal
    );
}

#[test]
fn rational_arithmetic_reduces_before_checking_range() {
    let large = Rational::new(i64::MAX, 2).unwrap();
    assert_eq!(
        large
            .checked_mul(Rational::new(2, i64::MAX).unwrap())
            .unwrap(),
        Rational::new(1, 1).unwrap()
    );
    let minimum = Rational::new(i64::MIN, 1).unwrap();
    assert_eq!(
        minimum.checked_div(minimum).unwrap(),
        Rational::new(1, 1).unwrap()
    );
    assert_eq!(
        minimum.checked_mul(Rational::new(-1, 1).unwrap()),
        Err(Error::ArithmeticRange)
    );
    assert_eq!(Rational::new(1, i64::MIN), Err(Error::ArithmeticRange));
    assert_eq!(
        Rational::new(i64::MIN, i64::MIN).unwrap(),
        Rational::new(1, 1).unwrap()
    );
    assert_eq!(large.checked_mul(large), Err(Error::ArithmeticRange));
    assert_eq!(Rational::new(1, 0), Err(Error::DivisionByZero));
}

#[test]
fn denominator_approximation_uses_exact_distance_and_ties() {
    for (n, d, limit, expected) in [
        (3, 2, 1, "1"),
        (5, 2, 1, "2"),
        (-3, 2, 1, "-2"),
        (-5, 2, 1, "-3"),
        (355, 113, 10, "22/7"),
        (1, 4, 1, "0"),
        (10, 7, 5, "7/5"),
    ] {
        assert_eq!(
            Rational::new(n, d)
                .unwrap()
                .limit_denominator(limit)
                .unwrap()
                .to_string(),
            expected
        );
    }
    let approx = Number::approximate(2.0_f64.powf(1.0 / 3.0)).unwrap();
    assert_eq!(approx.limit_denominator(5).unwrap().to_string(), "5/4");
    assert_eq!(
        Rational::from_f64(0.1).unwrap(),
        Rational::new(3602879701896397, 36028797018963968).unwrap()
    );
    assert_eq!(
        Rational::from_f64(f64::MIN_POSITIVE),
        Err(Error::ArithmeticRange)
    );
    assert_eq!(
        Rational::from_f64(f64::INFINITY),
        Err(Error::ArithmeticRange)
    );
}

#[test]
fn denominator_approximation_matches_small_exhaustive_search() {
    for denominator in 1..40_i64 {
        for numerator in 0..80_i64 {
            for maximum in 1..10_i64 {
                for sign in [-1, 1] {
                    let mut best = (0_i64, 1_i64);
                    let mut distance = numerator;
                    for q in 1..=maximum {
                        for magnitude in 0..=(numerator * q / denominator + 1) {
                            let p = sign * magnitude;
                            let delta = (sign * numerator * q - p * denominator).abs();
                            if delta * best.1 < distance * q
                                || (delta * best.1 == distance * q && (q, p) < (best.1, best.0))
                            {
                                best = (p, q);
                                distance = delta;
                            }
                        }
                    }
                    let value = Rational::new(sign * numerator, denominator).unwrap();
                    assert_eq!(
                        value.limit_denominator(maximum).unwrap(),
                        Rational::new(best.0, best.1).unwrap(),
                        "{value}, limit {maximum}"
                    );
                }
            }
        }
    }
    assert!(
        Number::approximate(440.123456789)
            .unwrap()
            .limit_denominator(10000)
            .is_ok()
    );
    assert_eq!(
        Rational::new(i64::MIN, 3)
            .unwrap()
            .limit_denominator(1)
            .unwrap(),
        Rational::new(-3074457345618258603, 1).unwrap()
    );
}

#[test]
fn expressions_preserve_numeric_kind_and_boundaries() {
    for (text, expected) in [
        ("-9223372036854775808", "-9223372036854775808"),
        ("9223372036854775807", "9223372036854775807"),
        ("0.0000000000000000005", "1/2000000000000000000"),
        ("01\n/2", "1/2"),
        ("0^0", "1"),
    ] {
        let value = evaluate(text).unwrap();
        assert!(value.rational().is_some(), "{text}");
        assert_eq!(value.to_string(), expected);
    }
    assert!(evaluate("9^(1/2)").unwrap().rational().is_none());
    for text in [
        "--9223372036854775808",
        "9223372036854775807^2",
        "2^-63",
        "1e-20",
        "NaN",
        "inf",
        "1e99999999999999999999",
    ] {
        assert!(evaluate(text).is_err(), "{text}");
    }
}
