import pytest
from pydantic import ValidationError

from ufor.broadcast import BroadcastScore, provisional_sections


def test_planned_and_aired_programme_keep_live_decisions() -> None:
    data = {
        'name': 'show',
        'title': 'Show',
        'timebase': {'name': 'seconds', 'rate': {'numerator': 1}},
        'body': {
            'sources': [
                {'name': 'recording', 'kind': 'recorded'},
                {'name': 'guest', 'kind': 'live'},
                {'name': 'bed', 'kind': 'recorded'},
            ],
            'sections': [
                {
                    'name': 'opening',
                    'source': 'recording',
                    'start': {'kind': 'at', 'tick': 0},
                    'end': {'kind': 'duration', 'duration': 60},
                },
                {
                    'name': 'guest',
                    'source': 'guest',
                    'start': {
                        'kind': 'cue',
                        'cue': 'guest-ready',
                        'earliest': 60,
                        'deadline': 120,
                    },
                    'end': {
                        'kind': 'cue_or_source_end',
                        'cue': 'guest-end',
                        'maximum': 300,
                    },
                    'unavailable': {'kind': 'replacement', 'source': 'bed'},
                    'capture': True,
                },
            ],
            'aired': {
                'events': [
                    {'tick': 0, 'ordinal': 0, 'section': 'opening', 'action': 'start'},
                    {
                        'tick': 60,
                        'ordinal': 1,
                        'section': 'guest',
                        'action': 'replacement',
                    },
                ]
            },
        },
    }
    score = BroadcastScore.model_validate(data)
    assert score.body.aired.events[1].action == 'replacement'
    assert provisional_sections(score.body) == ['guest']
    data['body']['sections'][0]['start'] = {'kind': 'after', 'section': 'guest'}
    data['body']['sections'][1]['start'] = {'kind': 'after', 'section': 'opening'}
    with pytest.raises(ValidationError, match='cycle'):
        BroadcastScore.model_validate(data)
