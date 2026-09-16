"""Pure TOML interchange and schema for the implemented document profiles."""

import tomlkit
from pydantic import TypeAdapter

from .arrangement import ArrangementScore
from .automation import AutomationScore
from .binding import BindingScore
from .broadcast import BroadcastScore
from .envelope import EnvelopeScore
from .fixture import FixtureScore
from .lfo import LFOScore
from .light_animation import AnimationScore
from .musical import OscillatorScore, ScaleScore, TuningScore
from .preset import PresetScore
from .recording import RecordingScore
from .samples.instrument import InstrumentScore
from .score_types import ScoreValue
from .sequence import SequenceScore
from .slideshow import SlideshowScore
from .synth import SynthInstrumentScore


def parse_score(
    text: str,
) -> (
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
    | PresetScore
):
    return TypeAdapter(ScoreValue).validate_python(tomlkit.parse(text))


def score_toml(
    value: ArrangementScore
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
) -> str:
    validated = TypeAdapter(ScoreValue).validate_python(value.model_dump())
    data = validated.model_dump(mode='json', exclude_none=True)
    _check_toml_arrays(data)
    return tomlkit.dumps(data)


def score_schema() -> dict[str, object]:
    return TypeAdapter(ScoreValue).json_schema()


def _check_toml_arrays(value: object) -> None:
    if isinstance(value, list):
        if any(v is None for v in value):
            raise ValueError(
                'TOML cannot represent null array arguments; use JSON to preserve them'
            )
        for item in value:
            _check_toml_arrays(item)
    elif isinstance(value, dict):
        for item in value.values():
            _check_toml_arrays(item)
