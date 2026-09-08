"""Musical definitions in the common document envelope."""

from typing import Literal

from .document import Document
from .oscillator import Oscillator
from .scale import Scale
from .tuning import Tuning


class TuningDocument(Document):
    kind: Literal['tuning'] = 'tuning'
    body: Tuning


class ScaleDocument(Document):
    kind: Literal['scale'] = 'scale'
    body: Scale


class OscillatorDocument(Document):
    kind: Literal['oscillator'] = 'oscillator'
    body: Oscillator
