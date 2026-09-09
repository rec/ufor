import json
import re
from fractions import Fraction
from pathlib import Path

import pytest
import tomlkit
from pydantic import ValidationError

from ufor import envelope, lfo
from ufor.base import Model
from ufor.codec import document_toml, parse_document
from ufor.oscillator import Waveform, shape_value


class EnvelopeObservation(envelope.EnvelopeValue):
    at: Fraction


class EnvelopeCase(Model):
    name: str
    definition: envelope.Envelope
    events: list[envelope.EnvelopeEvent]
    observations: list[EnvelopeObservation]


class LFOObservation(lfo.LFOValue):
    at: Fraction


class LFOCase(Model):
    name: str
    definition: lfo.LFO
    events: list[lfo.LFOEvent]
    observations: list[LFOObservation]


def check_envelope(case: EnvelopeCase, extra_observations: bool) -> None:
    state = envelope.initial_envelope(case.definition, Fraction(0))
    remaining = iter(case.events)
    event = next(remaining, None)
    for probe in case.observations:
        while event is not None and event.at <= probe.at:
            if extra_observations:
                envelope.envelope_at(case.definition, state, (state.at + event.at) / 2)
                state = envelope.EnvelopeState.model_validate_json(
                    state.model_dump_json()
                )
            state = envelope.envelope_event(case.definition, state, event)
            event = next(remaining, None)
        actual = envelope.envelope_at(case.definition, state, probe.at)
        assert actual.value == pytest.approx(probe.value, abs=TOLERANCE, rel=0)
        assert actual.status == probe.status
        assert actual.segment == probe.segment


def check_lfo(case: LFOCase, extra_observations: bool) -> None:
    state = lfo.initial_lfo(case.definition, Fraction(0))
    remaining = iter(case.events)
    event = next(remaining, None)
    for probe in case.observations:
        while event is not None and event.at <= probe.at:
            if extra_observations:
                lfo.lfo_at(case.definition, state, (state.at + event.at) / 2)
                state = lfo.LFOState.model_validate_json(state.model_dump_json())
            state = lfo.lfo_event(case.definition, state, event)
            event = next(remaining, None)
        actual = lfo.lfo_at(case.definition, state, probe.at)
        assert actual.phase == probe.phase
        assert actual.value == pytest.approx(probe.value, abs=TOLERANCE, rel=0)
        assert actual.weight == pytest.approx(probe.weight, abs=TOLERANCE, rel=0)


def test_release_interrupts_every_stage_without_restarting() -> None:
    definition = ENVELOPES['adsr with delay and hold'].definition
    for at, level in [('1/2', 0), ('2', 0.5), ('7/2', 1), ('5', 0.75), ('7', 0.5)]:
        state = envelope.initial_envelope(definition, Fraction(0))
        state = envelope.envelope_event(
            definition,
            state,
            envelope.EnvelopeEvent(at=Fraction(0), ordinal=0, action='trigger'),
        )
        release_at = Fraction(at)
        state = envelope.envelope_event(
            definition,
            state,
            envelope.EnvelopeEvent(at=release_at, ordinal=0, action='release'),
        )
        assert envelope.envelope_at(definition, state, release_at).value == level
        state = envelope.envelope_event(
            definition,
            state,
            envelope.EnvelopeEvent(at=release_at + 1, ordinal=0, action='release'),
        )
        assert (
            envelope.envelope_at(definition, state, release_at + 1).value == level / 2
        )
        assert (
            envelope.envelope_at(definition, state, release_at + 2).status == 'complete'
        )


def test_curved_release_reaches_exact_zero() -> None:
    definition = envelope.Envelope(
        segments=[envelope.Segment(duration=Fraction(0), target=1)],
        release=[envelope.Segment(duration=Fraction(1), target=0, curve=-5)],
    )
    state = envelope.initial_envelope(definition, Fraction(0))
    for ordinal, action in enumerate(['trigger', 'release']):
        state = envelope.envelope_event(
            definition,
            state,
            envelope.EnvelopeEvent.model_validate(
                {'at': '0', 'ordinal': ordinal, 'action': action}
            ),
        )
    assert envelope.envelope_at(
        definition, state, Fraction(1, 2)
    ).value == pytest.approx(0.07585818002124355, abs=TOLERANCE, rel=0)
    assert envelope.envelope_at(definition, state, Fraction(1)).value == 0


def test_independent_instances_and_replay_for_seeking() -> None:
    definition = ENVELOPES[
        'release interrupts attack and consumes its full duration'
    ].definition
    idle = envelope.initial_envelope(definition, Fraction(0))
    active = envelope.envelope_event(
        definition,
        idle,
        envelope.EnvelopeEvent(at=Fraction(0), ordinal=0, action='trigger'),
    )
    assert envelope.envelope_at(definition, idle, Fraction(1)).status == 'idle'
    assert envelope.envelope_at(definition, active, Fraction(1)).value == 0.5
    released = envelope.envelope_event(
        definition,
        active,
        envelope.EnvelopeEvent(at=Fraction(1), ordinal=0, action='release'),
    )
    with pytest.raises(ValueError, match='replay'):
        envelope.envelope_at(definition, released, Fraction(1, 2))
    assert envelope.envelope_at(definition, active, Fraction(1, 2)).value == 0.25
    oscillator = lfo.LFO(rate=Fraction(1, 4))
    first = lfo.initial_lfo(oscillator, Fraction(0))
    second = lfo.initial_lfo(oscillator, Fraction(1))
    assert lfo.phase_at(first, Fraction(2)) == Fraction(1, 2)
    assert lfo.phase_at(second, Fraction(2)) == Fraction(1, 4)


def test_equal_time_ordinals_are_strict_for_both_generators() -> None:
    definition = ENVELOPES['adsr with delay and hold'].definition
    state = envelope.initial_envelope(definition, Fraction(0))
    event = envelope.EnvelopeEvent(at=Fraction(1), ordinal=2, action='trigger')
    state = envelope.envelope_event(definition, state, event)
    for invalid in [
        event,
        envelope.EnvelopeEvent(at=Fraction(0), ordinal=3, action='release'),
    ]:
        with pytest.raises(ValueError, match='order'):
            envelope.envelope_event(definition, state, invalid)
    oscillator = lfo.LFO(rate=Fraction(1))
    lfo_state = lfo.initial_lfo(oscillator, Fraction(0))
    change = lfo.LFOEvent(at=Fraction(1), ordinal=0, action='rate', rate=Fraction(2))
    lfo_state = lfo.lfo_event(oscillator, lfo_state, change)
    with pytest.raises(ValueError, match='order'):
        lfo.lfo_event(oscillator, lfo_state, change)
    with pytest.raises(ValueError, match='replay'):
        lfo.lfo_at(oscillator, lfo_state, Fraction(0))


def test_rate_event_payload_is_required_only_for_rate_changes() -> None:
    for payload in [{'action': 'rate'}, {'action': 'reset', 'rate': '1'}]:
        with pytest.raises(ValidationError, match='rate events'):
            lfo.LFOEvent.model_validate({'at': '0', 'ordinal': 0, **payload})


def test_beat_controls_follow_supplied_tempo_positions_without_reset() -> None:
    definition = envelope.Envelope.model_validate(
        {
            'clock': 'beats',
            'segments': [{'duration': '4', 'target': 1}],
            'release': [{'duration': '0', 'target': 0}],
        }
    )
    oscillator = lfo.LFO.model_validate({'clock': 'beats', 'rate': '1/4'})
    state = envelope.initial_envelope(definition, Fraction(0))
    state = envelope.envelope_event(
        definition,
        state,
        envelope.EnvelopeEvent(at=Fraction(0), ordinal=0, action='trigger'),
    )
    phase = lfo.initial_lfo(oscillator, Fraction(0))
    # Host positions for 120 BPM until second 1, then 60 BPM.
    for seconds, beats in [('0', 0), ('1/2', 1), ('1', 2), ('2', 3)]:
        at = Fraction(beats)
        expected = beats / 4
        assert envelope.envelope_at(definition, state, at).value == expected, seconds
        assert lfo.phase_at(phase, at) == Fraction(beats, 4), seconds


def test_documented_modulation_examples_are_complete_documents() -> None:
    text = (Path(__file__).parents[1] / 'doc/modulation-format.md').read_text()
    examples = re.findall(r'```toml\n(.*?)```', text, re.DOTALL)
    assert examples
    for example in examples:
        document = parse_document(example)
        assert parse_document(document_toml(document)) == document


CASES = json.loads(
    (Path(__file__).parents[1] / 'conformance/modulation.json').read_text()
)
TOLERANCE = CASES['absolute_tolerance']
ENVELOPES = {c['name']: EnvelopeCase.model_validate(c) for c in CASES['envelopes']}
LFOS = [LFOCase.model_validate(c) for c in CASES['lfos']]


@pytest.mark.parametrize('case', ENVELOPES.values(), ids=list(ENVELOPES))
@pytest.mark.parametrize('extra_observations', [False, True])
def test_envelope_conformance(case: EnvelopeCase, extra_observations: bool) -> None:
    check_envelope(case, extra_observations)
    document = envelope.EnvelopeDocument(
        id='envelope', name=case.name, body=case.definition
    )
    assert parse_document(document_toml(document)) == document


@pytest.mark.parametrize('case', LFOS, ids=[c.name for c in LFOS])
@pytest.mark.parametrize('extra_observations', [False, True])
def test_lfo_conformance(case: LFOCase, extra_observations: bool) -> None:
    check_lfo(case, extra_observations)
    document = lfo.LFODocument(id='lfo', name=case.name, body=case.definition)
    assert parse_document(document_toml(document)) == document


@pytest.mark.parametrize('case', CASES['curves'])
def test_curve_conformance(case: dict[str, float]) -> None:
    assert envelope.curve_progress(case['progress'], case['curve']) == pytest.approx(
        case['value'], abs=TOLERANCE, rel=0
    )


@pytest.mark.parametrize('case', CASES['shapes'])
def test_shape_conformance(case: dict[str, str | float]) -> None:
    assert shape_value(
        Waveform(case['waveform']),
        Fraction(str(case['phase'])),
        Fraction(str(case['duty_cycle'])),
    ) == pytest.approx(case['value'], abs=TOLERANCE, rel=0)


@pytest.mark.parametrize('case', CASES['invalid_documents'])
def test_invalid_modulation_documents(case: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        parse_document(tomlkit.dumps({'id': 'invalid', 'name': 'Invalid', **case}))
