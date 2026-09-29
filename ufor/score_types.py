"""The supported score union, independent of interchange encoding."""

from typing import Annotated

from pydantic import Field

from .arrangement import ArrangementScore
from .automation import AutomationScore
from .binding import BindingScore
from .broadcast import BroadcastScore
from .fixture import FixtureScore
from .interface import Part
from .light_animation import AnimationScore
from .motion import MotionScore
from .musical import OscillatorScore, ScaleScore, TuningScore
from .performance_binding import PerformanceBindingScore
from .preset import PresetScore
from .recording import RecordingScore
from .samples.instrument import SampleInstrumentScore
from .sequence import SequenceScore
from .slideshow import SlideshowScore
from .synth import SynthInstrumentScore

ScoreValue = Annotated[
    ArrangementScore
    | AutomationScore
    | BindingScore
    | PerformanceBindingScore
    | BroadcastScore
    | FixtureScore
    | RecordingScore
    | SequenceScore
    | SlideshowScore
    | TuningScore
    | ScaleScore
    | OscillatorScore
    | MotionScore
    | SampleInstrumentScore
    | AnimationScore
    | SynthInstrumentScore
    | PresetScore,
    Field(discriminator='kind'),
]

Part.model_rebuild(_types_namespace={'ScoreValue': ScoreValue})
