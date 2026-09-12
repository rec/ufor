import pytest
from pydantic import ValidationError

from ufor.broadcast import BroadcastScore


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
                    'start': 'at',
                    'tick': 0,
                    'duration': 60,
                },
                {
                    'name': 'guest',
                    'source': 'guest',
                    'start': 'cue',
                    'cue': 'guest-ready',
                    'duration': 300,
                    'replacement': 'bed',
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
    assert (
        BroadcastScore.model_validate(data).body.aired.events[1].action == 'replacement'
    )
    data['body']['sections'][0]['start'] = 'after'
    data['body']['sections'][0]['after'] = 'guest'
    del data['body']['sections'][0]['tick']
    data['body']['sections'][1]['start'] = 'after'
    data['body']['sections'][1]['after'] = 'opening'
    del data['body']['sections'][1]['cue']
    with pytest.raises(ValidationError, match='cycle'):
        BroadcastScore.model_validate(data)
