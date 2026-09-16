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


def test_provisional_timing_propagates_in_dependency_order() -> None:
    from ufor.broadcast import Broadcast

    broadcast = Broadcast.model_validate(
        {
            'sources': [{'name': 'source', 'kind': 'recorded'}],
            'sections': [
                {
                    'name': 'third',
                    'source': 'source',
                    'start': {'kind': 'after', 'section': 'second'},
                    'end': {'kind': 'duration', 'duration': 10},
                },
                {
                    'name': 'fixed',
                    'source': 'source',
                    'start': {'kind': 'at', 'tick': 0},
                    'end': {'kind': 'duration', 'duration': 10},
                },
                {
                    'name': 'first',
                    'source': 'source',
                    'start': {'kind': 'cue', 'cue': 'go'},
                    'end': {'kind': 'duration', 'duration': 10},
                },
                {
                    'name': 'second',
                    'source': 'source',
                    'start': {'kind': 'after', 'section': 'first'},
                    'end': {'kind': 'duration', 'duration': 10},
                },
            ],
        }
    )
    assert provisional_sections(broadcast) == ['third', 'first', 'second']


@pytest.mark.parametrize(
    'kind,fields', [('at', {'tick': 0}), ('after', {'section': 'previous'})]
)
@pytest.mark.parametrize('window', ['earliest', 'deadline'])
def test_only_cue_starts_accept_windows(
    kind: str, fields: dict[str, object], window: str
) -> None:
    from ufor.broadcast import StartRule

    with pytest.raises(ValidationError, match='only cue starts'):
        StartRule.model_validate({'kind': kind, **fields, window: 1})
