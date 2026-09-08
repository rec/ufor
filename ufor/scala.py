"""Scala scale text conversion. File discovery and encoding belong to the host."""

from .expression import evaluate
from .number import uncents
from .tuning import RatioTable


def parse_scala(text: str, name: str = '') -> RatioTable:
    lines = [s for i in text.splitlines() if (s := i.strip()) and not s.startswith('!')]
    if len(lines) < 3:
        raise ValueError('Scala scale requires a description, count and pitches')
    description, count, *pitches = lines
    if int(count) != len(pitches) or int(count) < 1:
        raise ValueError('Scala pitch count does not match the entries')
    entries = [_pitch(i.split()[0]) for i in pitches]
    return RatioTable(
        values=['1', *entries[:-1]],
        repeat_ratio=entries[-1],
        name=name,
        desc=description,
    )


def scala_text(table: RatioTable) -> str:
    if table.repeat_ratio is None or evaluate(table.values[0]) != 1:
        raise ValueError('Scala export requires a repeating table beginning at unison')
    entries = [_scala_pitch(i) for i in [*table.values[1:], table.repeat_ratio]]
    return '\n'.join(
        [
            f'! {table.name}',
            '!',
            table.desc or 'Untitled',
            str(len(entries)),
            '!',
            *entries,
            '',
        ]
    )


def _pitch(text: str) -> str:
    # In Scala a decimal point marks cents. Integer and fraction entries are ratios.
    return f'2^({text}/1200)' if '.' in text else text


def _scala_pitch(expression: str) -> str:
    value = evaluate(expression)
    # Scala accepts fractions of integers. Non-rational powers use cents.
    if isinstance(value, float):
        return f'{uncents(value):.12f}'
    return str(value)
