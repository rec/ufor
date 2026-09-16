"""Normalized analysis controls; acquisition and analysis belong to the host."""

from typing import Annotated

from pydantic import Field

from .base import Model


class AudioFeatures(Model):
    """One host-supplied observation at a logical light-frame boundary."""

    level: float = Field(ge=0, le=1)
    bass: float = Field(ge=0, le=1)
    mid: float = Field(ge=0, le=1)
    treble: float = Field(ge=0, le=1)
    onset: float = Field(ge=0, le=1)
    beat: float = Field(ge=0, le=1)
    spectrum: list[Annotated[float, Field(ge=0, le=1)]] = Field(min_length=1)
