from fractions import Fraction

import pytest
from pydantic import ValidationError

from ufor import envelfo, segments
from ufor.codec import parse_score, score_toml


def test_indefinite_segment_has_no_destination_or_curve() -> None:
    body = envelfo.Envelope.model_validate(
        {'segments': [{'duration': '1/4 s', 'to': 0.7}, {'duration': None}]}
    )
    assert isinstance(body.segments[1], segments.IndefiniteSegment)
    assert body.segments[1].model_dump() == {'duration': None}
    assert envelfo.Envelope.model_validate_json(body.model_dump_json()) == body
    for field in ('to', 'curve'):
        with pytest.raises(ValidationError):
            segments.IndefiniteSegment.model_validate({'duration': None, field: 0})


@pytest.mark.parametrize(
    'settings',
    [
        {'markers': [{'name': 'cue', 'position': '1/2'}]},
        {'playback': 'loop'},
        {'playback': 'ping_pong'},
    ],
)
def test_indefinite_envelopes_reject_normalized_playback(
    settings: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match='indefinite envelopes'):
        envelfo.Envelope.model_validate({'segments': [{'duration': None}], **settings})


def test_indefinite_stage_inherits_beats_and_round_trips_toml() -> None:
    document = envelfo.EnvelfoScore(
        name='held',
        title='Held',
        body=envelfo.Stages.model_validate(
            {
                'kind': 'stages',
                'clock': 'beats',
                'initial_stage': 'sustain',
                'stages': [
                    {
                        'name': 'sustain',
                        'envelfo': {
                            'kind': 'envelope',
                            'initial': 0.6,
                            'segments': [{'duration': None}],
                        },
                    }
                ],
            }
        ),
    )
    assert parse_score(score_toml(document)) == document
    assert (
        envelfo.EnvelfoEvent(at=Fraction(0), ordinal=0, action='advance').action
        == 'advance'
    )
    with pytest.raises(ValidationError):
        envelfo.Stage.model_validate({'name': 'old', 'envelfo': {'kind': 'hold'}})
