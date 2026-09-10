"""Pure TOML interchange and schema for the implemented document profiles."""

from typing import Annotated

import tomlkit
from pydantic import Field, TypeAdapter

from .arrangement import ArrangementScore
from .envelope import EnvelopeScore
from .lfo import LFOScore
from .musical import OscillatorScore, ScaleScore, TuningScore
from .recording import RecordingScore
from .samples.instrument import InstrumentScore
from .sequence import SequenceScore


def parse_score(
    text: str,
) -> (
    ArrangementScore
    | RecordingScore
    | SequenceScore
    | TuningScore
    | ScaleScore
    | OscillatorScore
    | EnvelopeScore
    | InstrumentScore
    | LFOScore
):
    return TypeAdapter(ScoreValue).validate_python(tomlkit.parse(text))


def score_toml(
    value: ArrangementScore
    | RecordingScore
    | SequenceScore
    | TuningScore
    | ScaleScore
    | OscillatorScore
    | EnvelopeScore
    | InstrumentScore
    | LFOScore,
) -> str:
    validated = TypeAdapter(ScoreValue).validate_python(value.model_dump())
    return tomlkit.dumps(validated.model_dump(mode='json', exclude_none=True))


def score_schema() -> dict[str, object]:
    return TypeAdapter(ScoreValue).json_schema()


ScoreValue = Annotated[
    ArrangementScore
    | RecordingScore
    | SequenceScore
    | TuningScore
    | ScaleScore
    | OscillatorScore
    | EnvelopeScore
    | InstrumentScore
    | LFOScore,
    Field(discriminator='kind'),
]
