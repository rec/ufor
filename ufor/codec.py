"""Pure TOML interchange and schema for the implemented document profiles."""

from typing import Annotated

import tomlkit
from pydantic import Field, TypeAdapter

from .arrangement import ArrangementScore
from .automation import AutomationScore
from .binding import BindingScore
from .envelope import EnvelopeScore
from .lfo import LFOScore
from .light_animation import AnimationScore
from .musical import OscillatorScore, ScaleScore, TuningScore
from .preset import PresetScore
from .recording import RecordingScore
from .samples.instrument import InstrumentScore
from .sequence import SequenceScore


def parse_score(
    text: str,
) -> (
    ArrangementScore
    | AutomationScore
    | BindingScore
    | RecordingScore
    | SequenceScore
    | TuningScore
    | ScaleScore
    | OscillatorScore
    | EnvelopeScore
    | InstrumentScore
    | LFOScore
    | AnimationScore
    | PresetScore
):
    return TypeAdapter(ScoreValue).validate_python(tomlkit.parse(text))


def score_toml(
    value: ArrangementScore
    | AutomationScore
    | BindingScore
    | RecordingScore
    | SequenceScore
    | TuningScore
    | ScaleScore
    | OscillatorScore
    | EnvelopeScore
    | InstrumentScore
    | LFOScore
    | AnimationScore
    | PresetScore,
) -> str:
    validated = TypeAdapter(ScoreValue).validate_python(value.model_dump())
    return tomlkit.dumps(validated.model_dump(mode='json', exclude_none=True))


def score_schema() -> dict[str, object]:
    return TypeAdapter(ScoreValue).json_schema()


ScoreValue = Annotated[
    ArrangementScore
    | AutomationScore
    | BindingScore
    | RecordingScore
    | SequenceScore
    | TuningScore
    | ScaleScore
    | OscillatorScore
    | EnvelopeScore
    | InstrumentScore
    | LFOScore
    | AnimationScore
    | PresetScore,
    Field(discriminator='kind'),
]
