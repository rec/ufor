"""Portable modulation scalars, identifiers, quantities and preparation limits."""

import math
import re
from bisect import bisect_right
from fractions import Fraction
from functools import cache
from importlib.resources import files
from typing import Annotated

import pydantic

from . import base, number
from .expression import evaluate


def identifier(value: str, info: pydantic.ValidationInfo) -> str:
    if info.context and info.context.get('portable'):
        data = _identifier_ranges()
        if not value or not _contains(data.lowercase, ord(value[0])):
            raise ValueError('Identifier must start with a portable lowercase letter')
        if any(
            not (
                _contains(data.lowercase, ord(c))
                or _contains(data.digits, ord(c))
                or c in '-_'
            )
            for c in value
        ):
            raise ValueError('Invalid portable identifier character')
        return value
    return base.identifier(value)


def scalar(value: object, info: pydantic.ValidationInfo) -> object:
    if info.context and info.context.get('portable'):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError('Portable scalars require JSON numbers')
        try:
            return finite(float(value))
        except OverflowError as error:
            raise ValueError('Scalar exceeds the f64 range') from error
    return value


def finite(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Scalar requires a finite f64 number')
    try:
        value = float(value)
    except OverflowError as error:
        raise ValueError('Scalar arithmetic exceeds the f64 range') from error
    if not math.isfinite(value):
        raise ValueError('Scalar arithmetic exceeds the f64 range')
    return value


def scalar_quantity(value: object, unit: str) -> float:
    if unit == 'hz_offset':
        unit = 'hz'
    if unit == 'phase' or (
        unit not in UNITS and unit not in ('logical', 'ratio', 'normalized')
    ):
        raise ValueError('Unknown scalar unit')
    if not isinstance(value, str):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError('Portable scalars require numbers or quantity strings')
        try:
            return finite(float(value))
        except OverflowError as error:
            raise ValueError('Scalar exceeds the f64 range') from error
    return _scalar_quantity(*_quantity(value, unit))


def scalar_rate(value: object) -> float:
    """A finite scalar reciprocal-second rate, without exact-rational limits."""
    if not isinstance(value, str):
        return scalar_quantity(value, 'hz')
    return _scalar_quantity(*_generator_quantity(value, 'per_second'))


def _scalar_quantity(tokens: list[str], factor: Fraction) -> float:
    result = finite(float(tokens[0]))
    for token in tokens[1:]:
        divisor = finite(float(token))
        if divisor == 0:
            raise ValueError('Quantity division by zero')
        result = finite(result / divisor)
    return finite(result * (float(factor.numerator) / float(factor.denominator)))


def exact_seconds(value: object) -> Fraction:
    result = exact_quantity(value, 'seconds')
    if result < 0:
        raise ValueError('Smoothing must be nonnegative')
    return result


def exact_quantity(value: object, unit: str) -> Fraction:
    """Parse a portable exact quantity without binary float time or widening."""
    if unit not in (
        'seconds',
        'beats',
        'hz',
        'phase',
        'ratio',
        'per_beat',
        'per_second',
    ):
        raise ValueError('Unknown exact unit')
    if type(value) is int:
        result = number.checked_fraction(value)
    elif isinstance(value, str):
        tokens, factor = _generator_quantity(value, unit)
        result = evaluate(tokens[0])
        for token in tokens[1:]:
            result = number.checked_divide(result, evaluate(token))
        result = number.checked_multiply(result, factor)
    elif isinstance(value, Fraction):
        result = number.checked_fraction(value.numerator, value.denominator)
    else:
        raise ValueError(
            'Exact quantities require integer or rational text, not float time'
        )
    assert isinstance(result, Fraction)
    return result


def _generator_quantity(text: str, unit: str) -> tuple[list[str], Fraction]:
    if len(text) > MAX_TEXT:
        raise ValueError('Quantity exceeds 4096 characters')
    if any(c in text for c in '\x1c\x1d\x1e\x1f'):
        raise ValueError('Unsupported quantity whitespace')
    factor = Fraction(1)
    numeric_unit = 'hz' if unit == 'per_second' else unit
    if unit in ('hz', 'per_beat', 'per_second'):
        aliases = UNITS['beats' if unit == 'per_beat' else 'seconds']
        if match := re.search(r'/\s*([A-Za-z_]+)(?=\s|/|$)', text):
            if match[1] not in aliases:
                raise ValueError('Incompatible reciprocal generator unit')
            factor = 1 / aliases[match[1]]
            text = text[: match.start()] + text[match.end() :]
            numeric_unit = 'ratio'
    tokens, scale = _quantity(text, numeric_unit)
    return tokens, scale * factor


def records(count: int, info: pydantic.ValidationInfo | None = None) -> None:
    maximum = MAX_RECORDS
    if info is not None and info.context and 'max_records' in info.context:
        maximum = number.bounded_integer(info.context['max_records'])
        if maximum < 0:
            raise ValueError('max_records must be nonnegative')
    if count > maximum:
        raise ValueError(f'Modulation preparation exceeds {maximum} records')


class _IdentifierRanges(pydantic.BaseModel, frozen=True):
    unicode_version: str
    lowercase: list[list[int]]
    digits: list[list[int]]


@cache
def _identifier_ranges() -> _IdentifierRanges:
    return _IdentifierRanges.model_validate_json(
        files('ufor').joinpath('identifier_ranges.json').read_bytes()
    )


def _contains(ranges: list[list[int]], value: int) -> bool:
    index = bisect_right(ranges, [value, 0x10FFFF]) - 1
    return index >= 0 and value <= ranges[index][1]


def _quantity(text: str, unit: str) -> tuple[list[str], Fraction]:
    if len(text) > MAX_TEXT:
        raise ValueError('Quantity exceeds 4096 characters')
    position = 0
    tokens: list[str] = []
    alias: str | None = None
    leading_alias = False
    while position < len(text):
        if text[position].isspace() and text[position] not in '\x1c\x1d\x1e\x1f':
            position += 1
            continue
        if not (match := TOKEN.match(text, position)):
            raise ValueError(
                'Expected scalar literals, rational quotients and one unit factor'
            )
        token = match[0]
        position = match.end()
        if token[0].isalpha() or token[0] == '_':
            if alias is not None:
                raise ValueError('Only one unit factor is supported')
            alias = token
            leading_alias = not tokens
            if tokens and tokens[-1] == '/':
                raise ValueError('A unit cannot replace a quotient denominator')
        else:
            tokens.append(token)
    if leading_alias and tokens:
        raise ValueError('Unit factors follow numeric quantities')
    if not tokens and alias is not None:
        tokens = ['1']
    if (
        not tokens
        or len(tokens) % 2 != 1
        or any(
            (v != '/') if i % 2 else not NUMERIC.fullmatch(v)
            for i, v in enumerate(tokens)
        )
    ):
        raise ValueError('Invalid rational quantity')
    if alias is None:
        factor = Fraction(1)
    else:
        if (factor := UNITS.get(unit, {}).get(alias)) is None:
            raise ValueError(f'Unsupported {unit} unit {alias}')
    return tokens[::2], factor


MAX_RECORDS = 10000
MAX_TEXT = 4096
Identifier = Annotated[
    str, pydantic.Field(max_length=MAX_TEXT), pydantic.AfterValidator(identifier)
]
Scalar = Annotated[float, pydantic.BeforeValidator(scalar)]
NUMERIC = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')
TOKEN = re.compile(NUMERIC.pattern + r'|[A-Za-z_]+|/')
UNITS = {
    'hz': {
        'Hz': Fraction(1),
        'hertz': Fraction(1),
        'kHz': Fraction(1000),
        'kilohertz': Fraction(1000),
        'mHz': Fraction(1, 1000),
        'millihertz': Fraction(1, 1000),
        'MHz': Fraction(1000000),
        'megahertz': Fraction(1000000),
    },
    'cents': {
        'cent': Fraction(1),
        'cents': Fraction(1),
        'musical_cent': Fraction(1),
        'semitone': Fraction(100),
        'octave': Fraction(1200),
        'oct': Fraction(1200),
    },
    'db': {'dB': Fraction(1), 'decibel': Fraction(1), 'decibels': Fraction(1)},
    'volts': {
        'V': Fraction(1),
        'volt': Fraction(1),
        'volts': Fraction(1),
        'mV': Fraction(1, 1000),
        'millivolt': Fraction(1, 1000),
        'millivolts': Fraction(1, 1000),
    },
    'seconds': {
        's': Fraction(1),
        'second': Fraction(1),
        'seconds': Fraction(1),
        'ms': Fraction(1, 1000),
        'millisecond': Fraction(1, 1000),
        'milliseconds': Fraction(1, 1000),
    },
    'beats': {'beat': Fraction(1), 'beats': Fraction(1)},
    'radians': {'rad': Fraction(1), 'radian': Fraction(1), 'radians': Fraction(1)},
    'phase': {
        'turn': Fraction(1),
        'turns': Fraction(1),
        'cycle': Fraction(1),
        'cycles': Fraction(1),
        'deg': Fraction(1, 360),
        'degree': Fraction(1, 360),
        'degrees': Fraction(1, 360),
    },
}
