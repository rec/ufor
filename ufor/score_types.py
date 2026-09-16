"""The supported score union, independent of interchange encoding."""

from typing import Annotated

from pydantic import Field

from .arrangement import ArrangementScore
from .automation import AutomationScore
from .binding import BindingScore
from .broadcast import BroadcastScore
from .envelope import EnvelopeScore
from .fixture import FixtureScore
from .interface import Part
from .lfo import LFOScore
from .light_animation import AnimationScore
from .musical import OscillatorScore, ScaleScore, TuningScore
from .preset import PresetScore
from .recording import RecordingScore
from .samples.instrument import InstrumentScore
from .sequence import SequenceScore
from .slideshow import SlideshowScore
from .synth import SynthInstrumentScore

ScoreValue = Annotated[
    ArrangementScore
    | AutomationScore
    | BindingScore
    | BroadcastScore
    | FixtureScore
    | RecordingScore
    | SequenceScore
    | SlideshowScore
    | TuningScore
    | ScaleScore
    | OscillatorScore
    | EnvelopeScore
    | InstrumentScore
    | LFOScore
    | AnimationScore
    | SynthInstrumentScore
    | PresetScore,
    Field(discriminator='kind'),
]

Part.model_rebuild(_types_namespace={'ScoreValue': ScoreValue})
