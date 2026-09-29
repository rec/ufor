"""Pure TOML interchange and schema for the implemented document profiles."""

from copy import deepcopy

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
from .samples.instrument import SampleInstrumentScore
from .score_types import ScoreValue
from .sequence import SequenceScore
from .slideshow import SlideshowScore
from .synth import SynthInstrumentScore

MAX_SCORE_CHARACTERS = 16 * 1024 * 1024


def migrate_score_v3(value: dict[str, object]) -> ScoreValue:
    """Convert one decoded version 3 score to the version 4 asset representation."""
    if value.get('format') != 'recs' or type(value.get('version')) is not int:
        raise ValueError('migration requires a recs version 3 score')
    if value['version'] != 3:
        raise ValueError('migration requires a recs version 3 score')
    data = deepcopy(value)
    data['version'] = 4
    kind = data.get('kind')
    if kind in {'instrument', 'recording'}:
        _migrate_assets(data.get('assets'))
    elif kind == 'slideshow':
        body = data.get('body')
        if not isinstance(body, dict):
            raise ValueError('version 3 slideshow body must be an object')
        _migrate_assets(body.get('assets'))
    return TypeAdapter(ScoreValue).validate_python(data)


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
    | SampleInstrumentScore
    | LFOScore
    | AnimationScore
    | SynthInstrumentScore
    | PresetScore
):
    if len(text) > MAX_SCORE_CHARACTERS:
        raise ValueError('score document exceeds 16777216 characters')
    try:
        data = tomlkit.parse(text).unwrap()
    except RecursionError as error:
        raise ValueError('score document is too deeply nested') from error
    _check_document_budget(data)
    return TypeAdapter(ScoreValue).validate_python(data)


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
    | SampleInstrumentScore
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


def _check_document_budget(value: object) -> None:
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > 100000 or depth > 64:
            raise ValueError('score document exceeds 100000 values or 64 levels')
        if isinstance(item, dict):
            pending.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            pending.extend((v, depth + 1) for v in item)


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


def _migrate_assets(value: object) -> None:
    if not isinstance(value, list):
        raise ValueError('version 3 score assets must be an array')
    for asset in value:
        if not isinstance(asset, dict):
            raise ValueError('version 3 asset must be an object')
        if 'location' in asset or 'content' in asset:
            raise ValueError('version 3 asset must use path, byte_length, and sha256')
        try:
            path = asset.pop('path')
            byte_length = asset.pop('byte_length')
            sha256 = asset.pop('sha256')
        except KeyError as e:
            raise ValueError(f'version 3 asset is missing {e.args[0]}') from e
        asset['location'] = {'kind': 'relative_file', 'path': path}
        asset['content'] = {'byte_length': byte_length, 'sha256': sha256}
