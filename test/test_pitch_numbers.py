"""Checked pitch arithmetic, independent of the expression parser."""

from fractions import Fraction
from math import inf

import pytest

from ufor import number


def test_cross_cancellation_preserves_representable_exact_results() -> None:
    large = Fraction(number.MAX_INTEGER, 2)
    assert number.checked_multiply(large, Fraction(2, number.MAX_INTEGER)) == 1
    assert number.checked_divide(number.MIN_INTEGER, number.MIN_INTEGER) == 1
    assert number.checked_fraction(number.MIN_INTEGER, number.MIN_INTEGER) == 1
    with pytest.raises(ValueError):
        number.checked_multiply(large, large)
    with pytest.raises(ValueError):
        number.checked_negate(number.MIN_INTEGER)
    with pytest.raises(ValueError):
        number.checked_power(Fraction(1, 2), 63)


def test_float_conversion_uses_its_exact_binary_fraction_within_64_bits() -> None:
    assert number.binary_fraction(0.1) == Fraction(3602879701896397, 36028797018963968)
    assert number.binary_fraction(float(number.MIN_INTEGER)) == number.MIN_INTEGER
    for value in (inf, 1e-200, float(number.MAX_INTEGER)):
        with pytest.raises(ValueError):
            number.binary_fraction(value)
    assert number.limit_denominator(440.123456789, 10000) == Fraction(
        440.123456789
    ).limit_denominator(10000)


def test_denominator_approximation_agrees_with_small_exact_reference_values() -> None:
    for n in range(-20, 21):
        for d in range(1, 21):
            value = Fraction(n, d)
            for limit in range(1, 9):
                assert number.limit_denominator(
                    value, limit
                ) == value.limit_denominator(limit)
    assert (
        number.limit_denominator(Fraction(number.MIN_INTEGER, 3), 1)
        == -3074457345618258603
    )


def test_arithmetic_failures_use_value_errors_and_fractional_powers_stay_floats() -> (
    None
):
    assert type(number.checked_power(9, Fraction(1, 2))) is float
    assert number.checked_power(0, 0) == 1
    with pytest.raises(ValueError):
        number.checked_divide(1, 0)
    with pytest.raises(ValueError):
        number.checked_power(2.0, 1025)
    with pytest.raises(ValueError):
        number.checked_difference(number.MAX_INTEGER, -1)
