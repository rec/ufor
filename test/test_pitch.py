import json
from fractions import Fraction
from pathlib import Path

import pytest

from ufor.codec import document_toml, parse_document
from ufor.expression import evaluate
from ufor.musical import OscillatorDocument, ScaleDocument, TuningDocument
from ufor.oscillator import Oscillator
from ufor.scala import parse_scala, scala_text
from ufor.scale import Scale
from ufor.tuning import Computed, FrequencyTable, IntervalPattern, RatioTable, Tuning

CASES = json.loads((Path(__file__).parents[1] / 'conformance/pitch.json').read_text())


@pytest.mark.parametrize('case', CASES['expressions'])
def test_pitch_expression_conformance(case: dict[str, str | float]) -> None:
    value = evaluate(str(case['text']))
    if 'exact' in case:
        assert isinstance(value, Fraction)
        assert value == Fraction(str(case['exact']))
    else:
        assert value == pytest.approx(case['approx'])


@pytest.mark.parametrize('expression', CASES['invalid_expressions'])
def test_pitch_language_rejects_other_operators_and_undefined_values(
    expression: str,
) -> None:
    with pytest.raises(ValueError):
        evaluate(expression)


def test_repeating_ratios_and_intervals_share_conformance_values() -> None:
    for name in ('ratios', 'intervals'):
        case = CASES[name]
        table = (
            RatioTable(values=case['values'], repeat_ratio=case['repeat_ratio'])
            if name == 'ratios'
            else IntervalPattern(intervals=case['values'])
        )
        for degree, expected in zip(case['degrees'], case['expected'], strict=True):
            assert table(degree) == Fraction(expected)


def test_equal_temperament_has_one_repeating_adjacent_interval() -> None:
    pattern = IntervalPattern(intervals=['2^(1/12)'])
    assert len(pattern.intervals) == 1
    assert pattern(12) == pytest.approx(2)
    assert pattern(-12) == pytest.approx(0.5)


def test_finite_tables_and_intervals_reject_both_outside_boundaries() -> None:
    frequencies = FrequencyTable(values=['440', '660'], first_note=69)
    assert frequencies(69) == 440
    assert frequencies(70) == 660
    ratios = RatioTable(values=['1', '3/2'])
    intervals = IntervalPattern(intervals=['3/2'], repeat=False)
    assert ratios(1) == intervals(1) == Fraction(3, 2)
    for table, indexes in (
        (frequencies, [68, 71]),
        (ratios, [-1, 2]),
        (intervals, [-1, 2]),
    ):
        for index in indexes:
            with pytest.raises(ValueError, match='outside'):
                table(index)


def test_mts_sized_frequency_table_remains_finite() -> None:
    tuning = Tuning(source=Computed())
    table = FrequencyTable(values=[str(tuning(i)) for i in range(128)])
    assert table(69) == 440
    with pytest.raises(ValueError, match='outside'):
        table(128)


def test_tuning_anchors_ratios_but_does_not_transpose_absolute_tables() -> None:
    tuning = Tuning(
        source=RatioTable(values=['1', '5/4'], repeat_ratio='2'), root_frequency='440/3'
    )
    assert tuning(70) == pytest.approx(440 / 3 * 5 / 4)
    absolute = Tuning(
        source=FrequencyTable(values=['440'], first_note=69),
        root_frequency='100',
        detune=1200,
    )
    assert absolute(69) == 880


def test_computed_limit_is_a_maximum_denominator() -> None:
    computed = Computed(limit=5)
    assert computed(4) == Fraction(5, 4)
    assert computed.as_ratios()(16) == Fraction(5, 2)


def test_scala_preserves_fractions_and_converts_decimal_cents() -> None:
    table = parse_scala('! example\nExample\n3\n5/4\n700.0\n2\n', name='example.scl')
    assert table(0) == 1
    assert table(1) == Fraction(5, 4)
    assert table(2) == pytest.approx(2 ** (700 / 1200))
    assert table(3) == 2
    assert table(-3) == Fraction(1, 2)
    exported = scala_text(table)
    assert '\n5/4\n' in exported
    assert parse_scala(exported).ratios == pytest.approx(table.ratios)
    with pytest.raises(ValueError, match='count'):
        parse_scala('Example\n2\n2\n')
    with pytest.raises(ValueError, match='repeating'):
        scala_text(RatioTable(values=['1']))


@pytest.mark.parametrize(
    'document',
    [
        TuningDocument(
            id='tuning',
            name='Ratios',
            body=Tuning(source=RatioTable(values=['1', '5/4'], repeat_ratio='2')),
        ),
        ScaleDocument(id='scale', name='Notes', body=Scale()),
        OscillatorDocument(
            id='oscillator', name='Triangle', body=Oscillator(key_scale=6)
        ),
    ],
)
def test_musical_documents_round_trip_through_common_codec(
    document: TuningDocument | ScaleDocument | OscillatorDocument,
) -> None:
    assert parse_document(document_toml(document)) == document


def test_oscillator_gain_uses_decibels_per_twelve_note_steps() -> None:
    oscillator = Oscillator(key_scale=20, key_scale_note=60)
    assert oscillator.gain(60) == 1
    assert oscillator.gain(72) == 10
    assert oscillator.gain(48) == 0.1
    with pytest.raises(ValueError):
        Oscillator(duty_cycle=1.1)


def test_scale_names_and_pitch_mapping_include_negative_notes() -> None:
    scale = Scale(offset=12)
    for note in range(-100, 100):
        assert scale.to_number(scale.to_name(note)) == note
    white_notes = Scale(notes='CDEFGAB')
    assert white_notes.to_name(7) == 'C1'
    assert white_notes.tuning_number(7) == 12
    half = Scale(
        note_names='CD',
        begin='C',
        root='C',
        end='D',
        intervals=[5, 5],
        accidentals='half',
    )
    assert half.to_name(1) == 'C^0'
    assert half.to_number('D♭0') == 3
