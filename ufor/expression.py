"""The bounded, fraction-preserving portable pitch grammar."""

import re
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, SkipValidation

from . import number


def evaluate(expression: str) -> Fraction | float:
    """Evaluate decimal literals, division, powers, signs and parentheses."""
    return _parse(expression, {}).number()


def positive(expression: str) -> str:
    number.positive_number(evaluate(expression))
    return expression


def evaluate_quantity(
    expression: str, unit: Literal['hertz', 'musical_cent']
) -> tuple[Fraction | float, bool]:
    """Evaluate the shared one-unit-factor subset, checking its dimension."""
    result = _parse(expression, FREQUENCIES if unit == 'hertz' else INTERVALS)
    if result.dimension is not None and (
        not isinstance(result.dimension, Fraction) or result.dimension != 1
    ):
        raise ValueError('Quantity has the wrong dimension')
    return result.number(), result.dimension is not None


class _Term(BaseModel, frozen=True):
    # Arithmetic validates results; avoid union coercion of exact/approximate values.
    value: SkipValidation[str | Fraction | float]
    depth: int = 0
    dimension: SkipValidation[Fraction | float | None] = None

    def number(self) -> Fraction | float:
        return _decimal(self.value) if isinstance(self.value, str) else self.value


class _Parser:
    def __init__(self, text: str, units: dict[str, Fraction]) -> None:
        self.text = text
        self.units = units
        self.position = 0
        self.parentheses = 0
        self.unit_count = 0

    def space(self) -> None:
        while self.position < len(self.text) and (
            self.text[self.position].isspace()
            and self.text[self.position] not in '\x1c\x1d\x1e\x1f'
        ):
            self.position += 1

    def take(self, token: str) -> bool:
        self.space()
        if self.text.startswith(token, self.position):
            self.position += len(token)
            return True
        return False

    def division(self, depth: int) -> _Term:
        value = self.quantity(depth)
        while self.take('/'):
            right = self.quantity(depth)
            dimension = value.dimension
            if right.dimension is not None:
                dimension = number.checked_negate(right.dimension)
            value = _term(
                number.checked_divide(value.number(), right.number()),
                max(value.depth, right.depth) + 1,
                dimension,
            )
        return value

    def signed(self, depth: int) -> _Term:
        if depth > MAX_EXPRESSION_DEPTH:
            raise ValueError('Pitch expression exceeds 64 levels')
        if self.take('+'):
            negative = False
        elif self.take('-'):
            negative = True
        else:
            value = self.atom(depth)
            if not self.take('^'):
                return value
            exponent = self.signed(depth + 1)
            if exponent.dimension is not None:
                raise ValueError('Pitch exponent must be dimensionless')
            power = exponent.number()
            if abs(number.as_float(power)) > MAX_POWER:
                raise ValueError('Pitch exponent exceeds 1024')
            dimension = (
                None
                if value.dimension is None
                else number.checked_multiply(value.dimension, power)
            )
            return _term(
                number.checked_power(value.number(), power),
                max(value.depth, exponent.depth) + 1,
                dimension,
            )
        value = self.signed(depth + 1)
        if isinstance(value.value, str):
            result = _decimal(value.value, negative)
        else:
            result = number.checked_negate(value.value) if negative else value.value
        return _term(result, value.depth + 1, value.dimension)

    def quantity(self, depth: int) -> _Term:
        value = self.signed(depth)
        if not self.units:
            return value
        self.space()
        if not (match := UNIT.match(self.text, self.position)):
            return value
        self.position = match.end()
        self.unit_count += 1
        if self.unit_count > 1:
            raise ValueError('Only one unit factor is supported')
        if (factor := self.units.get(match[0])) is None:
            raise ValueError(f'Unsupported unit {match[0]}')
        return _term(
            number.checked_multiply(value.number(), factor),
            value.depth + 1,
            Fraction(1),
        )

    def atom(self, depth: int) -> _Term:
        self.space()
        if self.units and UNIT.match(self.text, self.position):
            return _Term(value='1')
        if self.take('('):
            self.parentheses += 1
            if self.parentheses > MAX_EXPRESSION_DEPTH:
                raise ValueError('Pitch expression exceeds 64 parenthesis levels')
            value = self.division(depth)
            if not self.take(')'):
                raise ValueError('Missing closing pitch parenthesis')
            self.parentheses -= 1
            return value
        self.space()
        if not (match := NUMERIC.match(self.text, self.position)):
            raise ValueError('Expected a numeric pitch literal')
        self.position = match.end()
        return _Term(value=match[0])


def _parse(expression: str, units: dict[str, Fraction]) -> _Term:
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError('Pitch expression exceeds 4096 characters')
    parser = _Parser(expression, units)
    value = parser.division(0)
    parser.space()
    if parser.position != len(expression):
        raise ValueError('Unexpected pitch expression token')
    return value


def _term(
    value: Fraction | float, depth: int, dimension: Fraction | float | None
) -> _Term:
    if depth > MAX_EXPRESSION_DEPTH:
        raise ValueError('Pitch expression exceeds 64 syntax levels')
    return _Term(value=value, depth=depth, dimension=dimension)


def _decimal(text: str, negative: bool = False) -> Fraction:
    parts = re.split('[eE]', text, maxsplit=1)
    exponent = 0
    if len(parts) == 2:
        digits = parts[1].lstrip('+-').lstrip('0') or '0'
        if len(digits) > 4 or int(digits) > 4096:
            raise ValueError('Pitch numeric exponent exceeds 4096')
        exponent = -int(digits) if parts[1].startswith('-') else int(digits)
    mantissa = parts[0]
    fractional = len(mantissa.partition('.')[2])
    digits = mantissa.replace('.', '')
    stripped = digits.rstrip('0')
    power = exponent - fractional + len(digits) - len(stripped)
    digits = stripped.lstrip('0') or '0'
    if len(digits) > 20 or (len(digits) == 20 and digits > str(number.MAX_UNSIGNED)):
        raise ValueError('Pitch literal exceeds the 64-bit domain')
    numerator, denominator = int(digits), 1
    if numerator == 0:
        return Fraction(0)
    if power >= 0:
        for _ in range(power):
            if numerator > number.MAX_UNSIGNED // 10:
                raise ValueError('Pitch literal exceeds the 64-bit domain')
            numerator *= 10
    else:
        for factor in (2, 5):
            for _ in range(-power):
                if numerator % factor == 0:
                    numerator //= factor
                else:
                    if denominator > number.MAX_UNSIGNED // factor:
                        raise ValueError('Pitch literal exceeds the 64-bit domain')
                    denominator *= factor
    return number.checked_fraction(-numerator if negative else numerator, denominator)


MAX_EXPRESSION_LENGTH = 4096
MAX_EXPRESSION_DEPTH = 64
MAX_POWER = 1024
NUMERIC = re.compile(r'(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')
UNIT = re.compile('[A-Za-z_]+')
FREQUENCIES = {
    'Hz': Fraction(1),
    'hertz': Fraction(1),
    'kHz': Fraction(1000),
    'kilohertz': Fraction(1000),
    'mHz': Fraction(1, 1000),
    'millihertz': Fraction(1, 1000),
    'MHz': Fraction(1000000),
    'megahertz': Fraction(1000000),
}
INTERVALS = {
    'cent': Fraction(1),
    'cents': Fraction(1),
    'musical_cent': Fraction(1),
    'semitone': Fraction(100),
    'octave': Fraction(1200),
    'oct': Fraction(1200),
}
