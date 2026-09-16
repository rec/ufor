import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from ufor.base import FiniteScalar, Identifier
from ufor.binding import ParameterMapping
from ufor.broadcast import StartRule
from ufor.fixture import ChannelEncoding
from ufor.interface import ScoreReference
from ufor.samples.instrument import SampleInstrument
from ufor.scale import Scale
from ufor.slideshow import CaptionTrack, Transition

CASES = json.loads(
    (Path(__file__).parents[1] / 'conformance/validation.json').read_text()
)
MODELS = {
    'ScoreReference': ScoreReference,
    'Scale': Scale,
    'StartRule': StartRule,
    'ChannelEncoding': ChannelEncoding,
    'ParameterMapping': ParameterMapping,
    'Transition': Transition,
    'CaptionTrack': CaptionTrack,
    'SampleInstrument': SampleInstrument,
}


@pytest.mark.parametrize('value', CASES['identifiers']['valid'])
def test_unicode_identifiers_preserve_authored_spelling(value: str) -> None:
    assert TypeAdapter(Identifier).validate_python(value) == value


@pytest.mark.parametrize('value', CASES['identifiers']['invalid'])
def test_nonidentifier_text_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(Identifier).validate_python(value)


@pytest.mark.parametrize(
    'value', [float('inf'), float('-inf'), float('nan'), True, '1']
)
def test_finite_scalar_contract_applies_outside_models(value: object) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(FiniteScalar).validate_python(value)


@pytest.mark.parametrize('case', CASES['rejected'], ids=lambda c: c['rule'])
def test_portable_semantic_rejections(case: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        MODELS[case['model']].model_validate(case['value'])
