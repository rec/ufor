import json
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.codec import parse_score, score_toml
from ufor.musical import OscillatorScore
from ufor.oscillator import Oscillator, Waveform, shape_value


def test_declarations_and_shapes_match_shared_vectors() -> None:
    vectors = json.loads(
        (Path(__file__).parents[1] / 'conformance/oscillator.json').read_text()
    )
    for spec in vectors['definitions']:
        oscillator = Oscillator.model_validate(spec['oscillator'])
        assert oscillator.waveform == spec['waveform']
        assert oscillator.duty_cycle == Fraction(spec['duty'])
        assert float(oscillator.duty_cycle) == spec['duty_f64']
        for note, gain in spec['gains']:
            assert oscillator.gain(note) == pytest.approx(gain)
    for waveform, phase, duty, value in vectors['shape']:
        assert shape_value(Waveform(waveform), Fraction(phase), Fraction(duty)) == value
    for duty in vectors['invalid_duties']:
        with pytest.raises((ValidationError, ZeroDivisionError)):
            Oscillator.model_validate({'duty_cycle': duty})


def test_oscillator_score_preserves_its_header_and_exact_body() -> None:
    vectors = json.loads(
        (Path(__file__).parents[1] / 'conformance/oscillator.json').read_text()
    )
    document = vectors['score']
    score = OscillatorScore.model_validate(document)
    assert score.tags == ['#oscillator', '#square']
    assert score.body.duty_cycle == Fraction(document['body']['duty_cycle'])
    assert score.body.gain(72) == pytest.approx(10)
    assert parse_score(score_toml(score)) == score
    assert OscillatorScore.model_validate_json(score.model_dump_json()) == score
    for overrides in vectors['invalid_score_overrides']:
        with pytest.raises(ValidationError):
            OscillatorScore.model_validate(document | overrides)
