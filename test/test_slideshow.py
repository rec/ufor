import pytest
from pydantic import ValidationError

from ufor.slideshow import DirectorySelection, SlideshowScore, resolve_selection


def test_bulk_selection_is_sorted_and_excludes_patterns() -> None:
    selection = DirectorySelection(
        name='travel',
        directory='photos/travel',
        recursive=True,
        include=['*.jpg', '*.png'],
        exclude=['draft-*', 'duplicate.jpg'],
    )
    assert resolve_selection(
        selection,
        [
            'photos/travel/b.jpg',
            'photos/travel/a.png',
            'photos/travel/draft-x.jpg',
            'photos/travel/duplicate.jpg',
            'photos/other/a.jpg',
        ],
    ) == ['photos/travel/a.png', 'photos/travel/b.jpg']


def test_still_show_requires_accessibility_and_replayable_decisions() -> None:
    data = {
        'name': 'travel',
        'title': 'Travel',
        'timebase': {'name': 'seconds', 'rate': {'numerator': 1}},
        'body': {
            'assets': [
                {
                    'name': 'first',
                    'path': 'photos/first.jpg',
                    'encoding': 'jpeg',
                    'byte_length': 1,
                    'sha256': '0' * 64,
                },
                {
                    'name': 'last',
                    'path': 'photos/last.jpg',
                    'encoding': 'jpeg',
                    'byte_length': 1,
                    'sha256': '1' * 64,
                },
            ],
            'items': [
                {'name': 'first', 'asset': 'first', 'duration': 8, 'alt': 'A mountain'},
                {
                    'name': 'last',
                    'asset': 'last',
                    'duration': 12,
                    'alt': 'A map',
                    'advance': 'manual',
                },
            ],
            'transitions': [
                {
                    'outgoing': 'first',
                    'incoming': 'last',
                    'kind': 'crossfade',
                    'duration': 2,
                }
            ],
            'run': {
                'events': [
                    {'tick': 0, 'ordinal': 0, 'action': 'enter', 'item': 'first'},
                    {'tick': 9, 'ordinal': 1, 'action': 'advance', 'item': 'last'},
                ]
            },
        },
    }
    assert SlideshowScore.model_validate(data).body.run is not None
    del data['body']['items'][0]['alt']
    with pytest.raises(ValidationError):
        SlideshowScore.model_validate(data)


def test_video_accompaniment_and_captions_are_portable_timeline_data() -> None:
    score = SlideshowScore.model_validate(
        {
            'name': 'film',
            'title': 'Film',
            'timebase': {'name': 'seconds', 'rate': {'numerator': 1}},
            'body': {
                'assets': [
                    {
                        'name': 'video',
                        'path': 'film.mov',
                        'encoding': 'mov',
                        'byte_length': 1,
                        'sha256': '0' * 64,
                    },
                    {
                        'name': 'audio',
                        'path': 'music.flac',
                        'encoding': 'flac',
                        'byte_length': 1,
                        'sha256': '1' * 64,
                    },
                ],
                'items': [
                    {
                        'name': 'scene',
                        'asset': 'video',
                        'visual_kind': 'video',
                        'source_start': 2,
                        'source_end': 12,
                        'duration': 10,
                        'alt': 'A train arrives',
                    }
                ],
                'accompaniment': {
                    'asset': 'audio',
                    'start': 0,
                    'source_start': 0,
                    'source_end': 10,
                },
                'manual_audio': 'pause',
                'captions': [
                    {
                        'language': 'en',
                        'captions': [
                            {
                                'start': 1,
                                'end': 3,
                                'language': 'en',
                                'text': 'A train approaches.',
                            }
                        ],
                    }
                ],
            },
        }
    )
    assert score.body.items[0].visual_kind == 'video'
