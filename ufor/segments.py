"""Shared authored segments for envelopes and timeline curves."""

from pydantic import Field

from . import control
from .base import Model


class Segment(Model):
    duration: control.Rational = Field(ge=0)
    to: float
    curve: float = 0
