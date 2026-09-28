"""Shared authored segments for envelopes and timeline curves."""

from pydantic import Field, StrictBool

from . import control
from .base import FiniteScalar, Model


class Segment(Model):
    duration: control.Rational = Field(ge=0)
    to: FiniteScalar | StrictBool
    curve: float = 0
