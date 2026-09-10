"""Common score header. Domain bodies add their own required fields."""

from typing import Literal

from pydantic import Field, field_validator

from .base import Model
from .selector import ScoreName, Tags


class Score(Model):
    format: Literal['recs'] = 'recs'
    version: Literal[3] = 3
    name: ScoreName
    title: str = Field(min_length=1)
    tags: Tags = Field(default_factory=list)

    @field_validator('version', mode='before')
    @classmethod
    def integer_version(cls, value: object) -> object:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError('version must be integer 3')
        return value
