"""Exact generator quantities and per-operation preparation budgets."""

from . import number


def record_limit(value: object = 10000) -> int:
    if type(value) is not int or not 0 <= value <= number.MAX_INTEGER:
        raise ValueError('max_records must be a nonnegative signed 64-bit integer')
    return value


def check_records(count: int, maximum: int = 10000) -> None:
    if count > record_limit(maximum):
        raise ValueError(f'Generator preparation exceeds {maximum} records')


def preparation_records(value: object, max_records: int = 10000) -> int:
    """Count declared records and references without expanding shared children.

    This is a preparation bound, not structural generator validation. Metadata
    strings are covered by the independent document budget.
    """
    maximum = record_limit(max_records)
    pending = [value]
    count = int(isinstance(value, dict))
    check_records(count, maximum)
    while pending:
        item = pending.pop()
        if not isinstance(item, dict):
            continue
        for key, child in item.items():
            if key in MAPPING_RECORDS and isinstance(child, dict):
                count += len(child)
                check_records(count, maximum)
                pending.extend(child.values())
            elif key in SEQUENCE_RECORDS and isinstance(child, (list, tuple)):
                count += len(child)
                check_records(count, maximum)
                pending.extend(child)
            elif key in REFERENCE_LISTS and isinstance(child, (list, tuple)):
                count += len(child)
            elif key in REFERENCE_MAPS and isinstance(child, dict):
                count += len(child)
            elif key in CHILD_RECORDS and isinstance(child, dict):
                count += 1
                pending.append(child)
            check_records(count, maximum)
    return count


MAPPING_RECORDS = ('envelfos', 'parameters', 'controls')
SEQUENCE_RECORDS = (
    'segments',
    'release',
    'markers',
    'stages',
    'transitions',
    'events',
    'event_connections',
    'bindings',
    'sources',
    'routes',
    'points',
    'parameters',
)
REFERENCE_LISTS = ('inputs', 'from', 'from_stages')
REFERENCE_MAPS = ('outputs', 'event_outputs')
CHILD_RECORDS = ('body', 'envelfo', 'modulation')
