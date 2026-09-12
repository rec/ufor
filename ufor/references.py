"""Structured content references, independent of CLI selector spelling."""

from pydantic import Field

from .base import Model


class RecordSelector(Model):
    source: str = Field(min_length=1)
    track: str = Field(min_length=1)
    channel: int | None = Field(default=None, ge=0, strict=True)
