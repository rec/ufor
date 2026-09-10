"""Musical definitions in the common document envelope."""

from typing import Literal

from .oscillator import Oscillator
from .scale import Scale
from .score import Score
from .tuning import Tuning


class TuningScore(Score):
    kind: Literal['tuning'] = 'tuning'
    body: Tuning


class ScaleScore(Score):
    kind: Literal['scale'] = 'scale'
    body: Scale


class OscillatorScore(Score):
    kind: Literal['oscillator'] = 'oscillator'
    body: Oscillator
