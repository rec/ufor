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


def test_inherited_advance_is_distinct_from_explicit_automatic() -> None:
    from ufor.slideshow import Slideshow

    data = {
        'assets': [
            {
                'name': 'photo',
                'path': 'photo.jpg',
                'encoding': 'jpeg',
                'byte_length': 1,
                'sha256': '0' * 64,
            }
        ],
        'default_advance': 'cue',
        'items': [
            {
                'name': 'first',
                'asset': 'photo',
                'duration': 5,
                'alt': 'Photo',
                'cue': 'go',
            },
            {
                'name': 'second',
                'asset': 'photo',
                'duration': 5,
                'alt': 'Photo',
                'advance': 'automatic',
            },
        ],
    }
    show = Slideshow.model_validate(data)
    assert show.items[0].advance is None
    assert show.items[1].advance == 'automatic'
    assert Slideshow.model_validate(show.model_dump()) == show
    with pytest.raises(ValidationError, match='effective cue'):
        Slideshow.model_validate(data | {'default_advance': 'manual'})
    data['transitions'] = [{'outgoing': 'first', 'incoming': 'second'}] * 2
    with pytest.raises(ValidationError, match='transition pair'):
        Slideshow.model_validate(data)


def test_cut_and_caption_language_cannot_contradict_their_contracts() -> None:
    from ufor.slideshow import CaptionTrack, Transition

    with pytest.raises(ValidationError, match='cut has no duration'):
        Transition(outgoing='first', incoming='second', duration=1)
    with pytest.raises(ValidationError, match='language must match'):
        CaptionTrack(
            language='en',
            captions=[{'start': 0, 'end': 1, 'language': 'fr', 'text': 'Bonjour'}],
        )
