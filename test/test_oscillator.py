import json
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

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
