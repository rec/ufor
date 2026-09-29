"""A deterministic, fraction-preserving pitch expression language."""

import ast
import math
import re
from fractions import Fraction

MAX_EXPRESSION_LENGTH = 4096
MAX_EXPRESSION_DEPTH = 64
MAX_POWER = 1024
MAX_FRACTION_BITS = 16384


def evaluate(expression: str) -> Fraction | float:
    """Evaluate numbers, division, powers, signs and parentheses, without eval."""
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError('Pitch expression exceeds 4096 characters')
    nesting = 0
    for character in expression:
        nesting += (character == '(') - (character == ')')
        if nesting > MAX_EXPRESSION_DEPTH:
            raise ValueError('Pitch expression exceeds 64 levels')
    if any(abs(int(e)) > 4096 for e in re.findall(r'[eE]([+-]?\d+)', expression)):
        raise ValueError('Pitch numeric exponent exceeds 4096')
    if not re.fullmatch(r'[0-9.eE\s/+^()\-]+', expression):
        raise ValueError('Expected a pitch expression using numbers, / and ^')
    source = expression.strip().replace('^', '**')
    try:
        tree = ast.parse(source, mode='eval')
    except (SyntaxError, RecursionError) as error:
        raise ValueError('Invalid pitch expression') from error
    try:
        value = _value(tree.body, source, 0)
        if not math.isfinite(value):
            raise ValueError('Pitch expression must be finite')
        return value
    except (ZeroDivisionError, OverflowError) as error:
        raise ValueError('Pitch expression is undefined or out of range') from error


def positive(expression: str) -> str:
    if evaluate(expression) <= 0:
        raise ValueError('Pitch values must be positive')
    return expression


def _value(node: ast.AST, source: str, depth: int) -> Fraction | float:
    if depth > MAX_EXPRESSION_DEPTH:
        raise ValueError('Pitch expression exceeds 64 levels')
    match node:
        case ast.Constant(value=value) if type(value) in (int, float):
            return _bounded(Fraction(ast.get_source_segment(source, node) or ''))
        case ast.UnaryOp(op=ast.UAdd(), operand=operand):
            return _value(operand, source, depth + 1)
        case ast.UnaryOp(op=ast.USub(), operand=operand):
            return -_value(operand, source, depth + 1)
        case ast.BinOp(left=left, op=ast.Div(), right=right):
            return _bounded(
                _value(left, source, depth + 1) / _value(right, source, depth + 1)
            )
        case ast.BinOp(left=left, op=ast.Pow(), right=right):
            base = _value(left, source, depth + 1)
            exponent = _value(right, source, depth + 1)
            if abs(exponent) > MAX_POWER:
                raise ValueError('Pitch exponent exceeds 1024')
            if isinstance(exponent, Fraction) and exponent.denominator == 1:
                if isinstance(base, Fraction) and (
                    max(base.numerator.bit_length(), base.denominator.bit_length())
                    * abs(int(exponent))
                    > MAX_FRACTION_BITS
                ):
                    raise ValueError('Pitch expression exceeds exact-number limit')
                return _bounded(base ** int(exponent))
            if base < 0:
                raise ValueError('Fractional powers require a nonnegative base')
            return float(base) ** float(exponent)
    raise ValueError('Only numeric literals, signs, / and ^ are supported')


def _bounded(value: Fraction | float) -> Fraction | float:
    if (
        isinstance(value, Fraction)
        and max(value.numerator.bit_length(), value.denominator.bit_length())
        > MAX_FRACTION_BITS
    ):
        raise ValueError('Pitch expression exceeds exact-number limit')
    return value
