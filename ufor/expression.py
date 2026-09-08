"""A deterministic, fraction-preserving pitch expression language."""

import ast
import math
import re
from fractions import Fraction


def evaluate(expression: str) -> Fraction | float:
    """Evaluate numbers, division, powers, signs and parentheses, without eval."""
    if not re.fullmatch(r'[0-9.eE\s/+^()\-]+', expression):
        raise ValueError('Expected a pitch expression using numbers, / and ^')
    source = expression.strip().replace('^', '**')
    try:
        tree = ast.parse(source, mode='eval')
    except SyntaxError as error:
        raise ValueError('Invalid pitch expression') from error
    try:
        value = _value(tree.body, source)
        if not math.isfinite(value):
            raise ValueError('Pitch expression must be finite')
        return value
    except (ZeroDivisionError, OverflowError) as error:
        raise ValueError('Pitch expression is undefined or out of range') from error


def positive(expression: str) -> str:
    if evaluate(expression) <= 0:
        raise ValueError('Pitch values must be positive')
    return expression


def _value(node: ast.AST, source: str) -> Fraction | float:
    match node:
        case ast.Constant(value=value) if type(value) in (int, float):
            return Fraction(ast.get_source_segment(source, node) or '')
        case ast.UnaryOp(op=ast.UAdd(), operand=operand):
            return _value(operand, source)
        case ast.UnaryOp(op=ast.USub(), operand=operand):
            return -_value(operand, source)
        case ast.BinOp(left=left, op=ast.Div(), right=right):
            return _value(left, source) / _value(right, source)
        case ast.BinOp(left=left, op=ast.Pow(), right=right):
            base, exponent = _value(left, source), _value(right, source)
            if isinstance(exponent, Fraction) and exponent.denominator == 1:
                return base ** int(exponent)
            if base < 0:
                raise ValueError('Fractional powers require a nonnegative base')
            return float(base) ** float(exponent)
    raise ValueError('Only numeric literals, signs, / and ^ are supported')
