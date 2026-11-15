import math
from collections.abc import Iterable
from fractions import Fraction

type NoteNumber = int  # May be negative
type PitchNumber = float | int | Fraction


def cents_to_ratio(f: PitchNumber) -> float:
    return math.exp2(float(f) / 1200)


def ratio_to_cents(c: PitchNumber) -> float:
    return math.log2(float(c)) * 1200


def bounded_integer(value: int) -> int:
    if type(value) is not int or not MIN_INTEGER <= value <= MAX_INTEGER:
        raise ValueError('Pitch integer exceeds the signed 64-bit domain')
    return value


def bounded_number(value: PitchNumber) -> PitchNumber:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('Pitch arithmetic exceeds the 64-bit domain')
    else:
        _parts(value)
    return value


def positive_number(value: PitchNumber) -> PitchNumber:
    bounded_number(value)
    if value <= 0:
        raise ValueError('Pitch result must be positive')
    return value


def checked_fraction(numerator: int, denominator: int = 1) -> Fraction:
    bounded_integer(numerator)
    bounded_integer(denominator)
    return _fraction(
        abs(numerator), abs(denominator), (numerator < 0) != (denominator < 0)
    )


def checked_negate(value: PitchNumber) -> Fraction | float:
    bounded_number(value)
    if isinstance(value, float):
        return -value
    numerator, denominator = _parts(value)
    if numerator == MIN_INTEGER:
        raise ValueError('Pitch arithmetic exceeds the 64-bit domain')
    return Fraction(-numerator, denominator)


def checked_multiply(left: PitchNumber, right: PitchNumber) -> Fraction | float:
    if isinstance(left, float) or isinstance(right, float):
        return _finite(as_float(left) * as_float(right))
    a, b = _parts(left)
    c, d = _parts(right)
    first, second = math.gcd(abs(a), d), math.gcd(abs(c), b)
    return _fraction(
        _unsigned_product(abs(a) // first, abs(c) // second),
        _unsigned_product(b // second, d // first),
        (a < 0) != (c < 0),
    )


def checked_divide(left: PitchNumber, right: PitchNumber) -> Fraction | float:
    if right == 0:
        raise ValueError('Pitch division by zero')
    if isinstance(left, float) or isinstance(right, float):
        return _finite(as_float(left) / as_float(right))
    a, b = _parts(left)
    c, d = _parts(right)
    first, second = math.gcd(abs(a), abs(c)), math.gcd(b, d)
    return _fraction(
        _unsigned_product(abs(a) // first, d // second),
        _unsigned_product(b // second, abs(c) // first),
        (a < 0) != (c < 0),
    )


def checked_power(base: PitchNumber, exponent: PitchNumber) -> Fraction | float:
    bounded_number(base)
    bounded_number(exponent)
    if not isinstance(exponent, float):
        n, d = _parts(exponent)
        if d == 1 and not isinstance(base, float):
            value = (
                checked_divide(1, base) if n < 0 else checked_fraction(*_parts(base))
            )
            remaining = abs(n)
            result = Fraction(1)
            while remaining:
                if remaining & 1:
                    result = checked_multiply(result, value)
                remaining >>= 1
                if remaining:
                    value = checked_multiply(value, value)
            return result
        integral = d == 1
    else:
        integral = False
    if base < 0 and not integral:
        raise ValueError('Fractional powers require a nonnegative base')
    try:
        return _finite(math.pow(as_float(base), as_float(exponent)))
    except (OverflowError, ValueError) as error:
        raise ValueError(
            'Pitch power is undefined or exceeds the 64-bit domain'
        ) from error


def checked_product(values: Iterable[PitchNumber]) -> PitchNumber:
    result: PitchNumber = Fraction(1)
    for value in values:
        result = checked_multiply(result, value)
    return result


def checked_difference(left: int, right: int) -> int:
    bounded_integer(left)
    bounded_integer(right)
    if (right > 0 and left < MIN_INTEGER + right) or (
        right < 0 and left > MAX_INTEGER + right
    ):
        raise ValueError('Pitch arithmetic exceeds the 64-bit domain')
    return left - right


def binary_fraction(value: float) -> Fraction:
    """Recover an exact binary float fraction without widening beyond 64 bits."""
    _finite(value)
    if value == 0:
        return Fraction(0)
    mantissa, exponent = math.frexp(abs(value))
    numerator = int(math.ldexp(mantissa, 53))
    exponent -= 53
    while numerator % 2 == 0:
        numerator //= 2
        exponent += 1
    if exponent >= 0:
        if exponent >= 64 or numerator > MAX_UNSIGNED >> exponent:
            raise ValueError('Pitch arithmetic exceeds the 64-bit domain')
        return _fraction(numerator << exponent, 1, value < 0)
    if -exponent >= 63:
        raise ValueError('Pitch arithmetic exceeds the 64-bit domain')
    return _fraction(numerator, 1 << -exponent, value < 0)


def limit_denominator(value: PitchNumber, maximum: int) -> Fraction:
    bounded_integer(maximum)
    if maximum < 1:
        raise ValueError('Denominator limit must be positive')
    target = (
        binary_fraction(value)
        if isinstance(value, float)
        else checked_fraction(*_parts(value))
    )
    if target.denominator <= maximum:
        return target
    if target.numerator < 0 and maximum == 1 and target.denominator == 2:
        return Fraction(target.numerator // 2)
    negative = target.numerator < 0
    magnitude = abs(target.numerator)
    n, d = target.denominator, magnitude % target.denominator
    p0, q0, p1, q1 = 1, 0, magnitude // target.denominator, 1
    while True:
        a = n // d
        if a > (maximum - q0) // q1:
            break
        p2, q2 = _convergent(p0, a, p1), q0 + a * q1
        p0, q0, p1, q1 = p1, q1, p2, q2
        n, d = d, n % d
        if d == 0:
            return checked_fraction(-p1 if negative else p1, q1)
    k = (maximum - q0) // q1
    p, q = _convergent(p0, k, p1), q0 + k * q1
    # Compare t-k with q/q1 in the continued-fraction tail, without cross-products.
    if _compare_positive(n - k * d, d, q, q1) >= 0:
        p, q = p1, q1
    return checked_fraction(-p if negative else p, q)


def as_float(value: PitchNumber) -> float:
    """Use the same component-to-f64 conversion as the native implementation."""
    bounded_number(value)
    if isinstance(value, Fraction):
        return float(value.numerator) / float(value.denominator)
    return float(value)


def _parts(value: int | Fraction) -> tuple[int, int]:
    if isinstance(value, Fraction):
        bounded_integer(value.numerator)
        if not 1 <= value.denominator <= MAX_INTEGER:
            raise ValueError('Pitch denominator exceeds the signed 64-bit domain')
        return value.numerator, value.denominator
    return bounded_integer(value), 1


def _fraction(numerator: int, denominator: int, negative: bool) -> Fraction:
    if denominator == 0:
        raise ValueError('Pitch division by zero')
    common = math.gcd(numerator, denominator)
    numerator, denominator = numerator // common, denominator // common
    signed = -numerator if negative else numerator
    bounded_integer(signed)
    if denominator > MAX_INTEGER:
        raise ValueError('Pitch denominator exceeds the signed 64-bit domain')
    return Fraction(signed, denominator)


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError('Pitch arithmetic exceeds the 64-bit domain')
    return value


def _unsigned_product(left: int, right: int) -> int:
    if right and left > MAX_UNSIGNED // right:
        raise ValueError('Pitch arithmetic exceeds the 64-bit domain')
    return left * right


def _convergent(initial: int, factor: int, value: int) -> int:
    if value and factor > (MAX_INTEGER - initial) // value:
        raise ValueError('Pitch arithmetic exceeds the 64-bit domain')
    return initial + factor * value


def _compare_positive(a: int, b: int, c: int, d: int) -> int:
    sign = 1
    while True:
        left, right = a // b, c // d
        if left != right:
            return sign * ((left > right) - (left < right))
        ar, cr = a % b, c % d
        if ar == 0 or cr == 0:
            return sign * ((ar > cr) - (ar < cr))
        a, b, c, d = b, ar, d, cr
        sign = -sign


MIN_INTEGER = -(1 << 63)
MAX_INTEGER = (1 << 63) - 1
MAX_UNSIGNED = (1 << 64) - 1
