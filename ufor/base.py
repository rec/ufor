"""Pure document values, independent of devices and rendering."""

from collections.abc import Hashable, Iterable
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


class Model(BaseModel, frozen=True):
    model_config = ConfigDict(
        extra='forbid', allow_inf_nan=False, validate_default=True
    )


def identifier(value: str) -> str:
    if not value or not value[0].islower():
        raise ValueError('must start with a lowercase letter')
    if any(not (c.islower() or c.isdigit() or c in '-_') for c in value):
        raise ValueError('must contain only lowercase letters, numbers, - or _')
    return value


def unique(values: Iterable[Hashable], label: str) -> None:
    seen: set[Hashable] = set()
    for value in values:
        if value in seen:
            raise ValueError(f'duplicate {label}: {value}')
        seen.add(value)


Identifier = Annotated[str, AfterValidator(identifier)]

Text = Annotated[str, Field(min_length=1)]
Key = Annotated[int, Field(strict=True)]
Bipolar = Annotated[float, Field(strict=True, ge=-1, le=1)]
Frame = Annotated[int, Field(strict=True, ge=0)]
Number = Annotated[float, Field(strict=True)]
Seconds = Annotated[float, Field(strict=True, ge=0)]
Frequency = Annotated[float, Field(strict=True, gt=0)]
PositiveSeconds = Annotated[float, Field(strict=True, gt=0)]
Positive = Annotated[float, Field(strict=True, gt=0)]
UnitInterval = Annotated[float, Field(strict=True, ge=0, le=1)]
