"""Portable tuning validation and effects on adjacent Python domains."""

import json
from fractions import Fraction

import pytest

from ufor import number
from ufor.codec import parse_score, score_toml
from ufor.musical import TuningScore
from ufor.oscillator import Oscillator
from ufor.scala import parse_scala, scala_text
from ufor.scale import Scale
from ufor.tuning import Computed, FrequencyTable, IntervalPattern, RatioTable, Tuning


@pytest.mark.parametrize('value', [True, 12.0, '12', number.MAX_INTEGER + 1])
def test_portable_context_rejects_nonportable_integers_in_python_and_json(
    value: object,
) -> None:
    source = {'notes_per_octave': value}
    authored = Computed.model_validate(source)
    with pytest.raises(ValueError):
        Computed.model_validate(source, context={'portable': True})
    with pytest.raises(ValueError):
        Computed.model_validate_json(json.dumps(source), context={'portable': True})
    if value == number.MAX_INTEGER + 1:
        with pytest.raises(ValueError):
            Computed.model_validate(authored, context={'portable': True})
    else:
        assert Computed.model_validate(
            authored, context={'portable': True}
        ).notes_per_octave == int(value)


@pytest.mark.parametrize(
    'source',
    [
        {'notes_per_octave': '12'},
        {'intervals': ['1'], 'repeat': 'false'},
    ],
)
def test_portable_context_reaches_nested_sources_and_score_codec(
    source: dict[str, object],
) -> None:
    value = {
        'kind': 'tuning',
        'name': 'test',
        'title': 'Test',
        'body': {'source': source},
    }
    TuningScore.model_validate(value)
    with pytest.raises(ValueError):
        TuningScore.model_validate(value, context={'portable': True})
    if 'notes_per_octave' in source:
        text = (
            "kind='tuning'\nname='test'\ntitle='Test'\n[body.source]\n"
            "notes_per_octave='12'"
        )
    else:
        text = (
            "kind='tuning'\nname='test'\ntitle='Test'\n[body.source]\n"
            "intervals=['1']\nrepeat='false'"
        )
    with pytest.raises(ValueError):
        parse_score(text)


def test_portable_revalidation_checks_edited_instances_at_every_tuning_level() -> None:
    table = RatioTable(ratios=['1'])
    tuning = Tuning(source=table)
    score = TuningScore(name='edited', title='Edited', body=tuning)
    assert isinstance(score.body.source, RatioTable)
    score.body.source.ratios[0] = '0'
    for model, value in [
        (RatioTable, score.body.source),
        (Tuning, score.body),
        (TuningScore, score),
    ]:
        with pytest.raises(ValueError):
            model.model_validate(value, context={'portable': True})
    with pytest.raises(ValueError):
        Tuning(source=score.body.source)
    with pytest.raises(ValueError):
        score_toml(score)


def test_broader_python_units_compile_to_portable_canonical_values() -> None:
    authored = Tuning(
        source=Computed(), root_frequency='1 gigahertz', detune_cents='2 semitones'
    )
    validated = Tuning.model_validate(authored, context={'portable': True})
    assert validated.root_frequency == '1000000000'
    assert validated.detune_cents == 200
    for value in ('1 gigahertz', '1 / (3 kHz)', '1Hz / 1Hz', '1Hz^2', '1^(1Hz)'):
        with pytest.raises(ValueError):
            FrequencyTable.model_validate(
                {'frequencies': [value]}, context={'portable': True}
            )
    with pytest.raises(ValueError):
        Tuning.model_validate(
            {'source': {}, 'detune_cents': '2 semitones'},
            context={'portable': True},
        )


def test_mutated_tables_still_enforce_preparation_and_positive_pitch_limits() -> None:
    table = RatioTable(ratios=['1'])
    table.ratios.extend(['1'] * 10000)
    with pytest.raises(ValueError):
        table(0)
    intervals = IntervalPattern(intervals=['1'])
    intervals.intervals[0] = '-1'
    with pytest.raises(ValueError):
        intervals(2)


def test_scale_keeps_naming_arithmetic_and_propagates_tuning_failures() -> None:
    scale = Scale()
    large = 1 << 80
    assert scale.to_number(scale.to_name(large)) == large
    tuning = Tuning(source=Computed())
    assert scale.frequency(tuning, 69) == 440
    with pytest.raises(ValueError):
        scale.frequency(tuning, large)


def test_scala_and_oscillator_arithmetic_have_separate_scopes() -> None:
    with pytest.raises(ValueError):
        parse_scala('Oversized\n1\n9223372036854775808/1\n')
    table = parse_scala('Just\n2\n5/4\n2\n')
    assert parse_scala(scala_text(table)).ratios == table.ratios
    duty = Fraction((1 << 100) + 1, (1 << 101) + 3)
    oscillator = Oscillator(duty_cycle=duty)
    assert oscillator.duty_cycle == duty
    assert oscillator.gain(oscillator.key_scale_note) == 1
