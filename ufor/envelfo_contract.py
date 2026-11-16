"""Exact generator quantities and per-operation preparation budgets."""

from fractions import Fraction
from typing import Literal, Self, get_args, get_origin

import pydantic

from . import modulation_contract, number
from .base import Model


class Definition(Model):
    """Portable definition validation, without changing authoring coercions."""

    @pydantic.model_validator(mode='wrap')
    @classmethod
    def portable_definition(
        cls,
        value: object,
        handler: pydantic.ModelWrapValidatorHandler[Self],
        info: pydantic.ValidationInfo,
    ) -> Self:
        if info.context and info.context.get('portable'):
            preparation_records(
                value, record_limit(info.context.get('max_records', 10000))
            )
        if isinstance(value, pydantic.BaseModel):
            value = definition_data(value)
        return handler(value)

    @pydantic.model_validator(mode='before')
    @classmethod
    def portable_fields(cls, value: object, info: pydantic.ValidationInfo) -> object:
        if not (
            info.context and info.context.get('portable') and isinstance(value, dict)
        ):
            return value
        result = dict(value)
        for name, field in cls.model_fields.items():
            if name not in value:
                continue
            item = value[name]
            annotation = field.annotation
            choices = get_args(annotation)
            if item is None and type(None) in choices:
                continue
            if any(get_origin(a) is Literal and item in get_args(a) for a in choices):
                continue
            if annotation is float or float in choices:
                if bool in choices and type(item) is bool:
                    continue
                result[name] = modulation_contract.scalar(item, info)
            if annotation is bool and type(item) is not bool:
                raise ValueError('Portable boolean fields require booleans')
            if annotation is int or int in choices:
                if type(item) is not int:
                    raise ValueError('Portable counters require integers')
                result[name] = number.bounded_integer(item)
            if annotation is Fraction:
                result[name] = modulation_contract.exact_quantity(item, 'ratio')
        return result

    model_config = pydantic.ConfigDict(revalidate_instances='always')


def text(value: str, info: pydantic.ValidationInfo) -> str:
    if info.context and info.context.get('portable'):
        if len(value) > 4096:
            raise ValueError('Generator text exceeds 4096 characters')
        value.encode('utf-8')
    return value


def definition_data(value: pydantic.BaseModel) -> dict[str, object]:
    """Snapshot actual fields, retaining invalid edited values for revalidation."""
    data = {f: getattr(value, f) for f in type(value).model_fields}
    if data.get('kind') == 'patch' and isinstance(data.get('envelfos'), dict):
        data['envelfos'] = {
            n: _inherited_data(v, data) for n, v in data['envelfos'].items()
        }
    if data.get('kind') == 'stages' and isinstance(data.get('stages'), list):
        stages: list[object] = []
        for stage in data['stages']:
            item = (
                {f: getattr(stage, f) for f in type(stage).model_fields}
                if isinstance(stage, pydantic.BaseModel)
                else stage
            )
            if isinstance(item, dict) and 'envelfo' in item:
                item = item | {'envelfo': _inherited_data(item['envelfo'], data)}
            stages.append(item)
        data['stages'] = stages
    if 'scope' in type(value).model_fields:
        for field in ('scope', 'clock', 'position_driver', 'origin'):
            if (
                field not in value.model_fields_set
                and data[field] == type(value).model_fields[field].default
            ):
                data.pop(field)
    return data


def _inherited_data(value: object, parent: dict[str, object]) -> object:
    if not isinstance(value, pydantic.BaseModel):
        return value
    kind = getattr(value, 'kind', None)
    if kind in ('patch', 'reference') or (
        parent.get('kind') == 'stages' and kind not in ('lfo', 'envelope')
    ):
        raise ValueError('Unsupported inherited generator kind')
    if 'scope' in type(value).model_fields:
        if (
            getattr(value, 'scope', None) != parent.get('scope')
            or getattr(value, 'clock', None) != parent.get('clock')
            or getattr(value, 'position_driver', None) != 'elapsed'
            or getattr(value, 'origin', None) is not None
        ):
            raise ValueError('Child generator settings must match their parent')
    data = definition_data(value)
    for field in ('scope', 'clock', 'position_driver', 'origin'):
        data.pop(field, None)
    return data


def duration_quantity(value: object) -> tuple[Fraction, str]:
    """Resolve an explicitly suffixed portable duration or a seconds integer."""
    if not isinstance(value, str):
        return modulation_contract.exact_quantity(value, 'seconds'), 'seconds'
    aliases = [
        t
        for t in modulation_contract.TOKEN.findall(value)
        if t[0].isalpha() or t[0] == '_'
    ]
    if len(aliases) != 1:
        raise ValueError('Segment duration text requires an explicit unit')
    unit = 'beats' if aliases[0] in modulation_contract.UNITS['beats'] else 'seconds'
    return modulation_contract.exact_quantity(value, unit), unit


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
    count = int(isinstance(value, (dict, pydantic.BaseModel)))
    check_records(count, maximum)
    while pending:
        item = pending.pop()
        if isinstance(item, pydantic.BaseModel):
            item = {f: getattr(item, f) for f in type(item).model_fields}
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
            elif key in CHILD_RECORDS and isinstance(child, (dict, pydantic.BaseModel)):
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
