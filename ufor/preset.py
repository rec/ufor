"""A named public-parameter configuration of another score."""

from typing import Literal

from pydantic import Field

from .base import Identifier
from .interface import ScoreVersion
from .score import Score


class PresetScore(Score):
    kind: Literal['preset'] = 'preset'
    score: ScoreVersion
    parameters: dict[Identifier, float] = Field(default_factory=dict)
