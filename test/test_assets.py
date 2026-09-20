import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.assets import (
    Asset,
    ContentIdentity,
    DownloadLocation,
    GitFileLocation,
    PythonProviderLocation,
    RelativeFileLocation,
    StreamLocation,
    VolumeFileLocation,
)
from ufor.codec import parse_score, score_toml
from ufor.slideshow import SlideshowScore


@pytest.mark.parametrize('path', ['../a.wav', '/a.wav', 'C:/a.wav', 'https://x/a', '.'])
def test_assets_require_contained_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        RelativeFileLocation(path=path)


def test_finite_asset_identity_round_trips() -> None:
    asset = Asset(
        name='take',
        location=RelativeFileLocation(path='audio/take.wav'),
        encoding='wav',
        content=ContentIdentity(byte_length=44, sha256='a' * 64),
    )
    assert Asset.model_validate_json(asset.model_dump_json()) == asset


@pytest.mark.parametrize(
    'location',
    [
        RelativeFileLocation(path='audio/take.wav'),
        VolumeFileLocation(volume_id='volume-1', path='takes/take.wav'),
        DownloadLocation(url='https://audio.example/take.wav'),
        GitFileLocation(
            repository='git://git.example/audio.git',
            commit='a' * 40,
            path='takes/take.wav',
        ),
    ],
)
def test_encoded_locations_require_content_identity(location: object) -> None:
    with pytest.raises(ValidationError, match='requires content identity'):
        Asset(name='take', location=location, encoding='wav')


@pytest.mark.parametrize(
    'location',
    [
        StreamLocation(url='https://radio.example/live', transport='icecast'),
        PythonProviderLocation(
            module='show_audio.inputs', function='feed', delivery='callback'
        ),
    ],
)
def test_live_locations_reject_content_identity(location: object) -> None:
    with pytest.raises(ValidationError, match='must not declare content identity'):
        Asset(
            name='live',
            location=location,
            encoding='float32',
            content={'byte_length': 4, 'sha256': '0' * 64},
        )


@pytest.mark.parametrize(
    'value',
    [
        {'url': 'take.wav'},
        {'url': 'http://audio.example/take.wav'},
        {'url': 'https://audio.example/take.wav#preview'},
        {'url': 'https://user:secret@audio.example/take.wav'},
    ],
)
def test_downloads_require_secret_free_https_urls(value: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        DownloadLocation(**value)


@pytest.mark.parametrize('commit', ['main', 'abc123', 'A' * 40])
def test_git_locations_require_full_lowercase_object_ids(commit: str) -> None:
    with pytest.raises(ValidationError):
        GitFileLocation(
            repository='ssh://git@git.example/audio.git',
            commit=commit,
            path='take.wav',
        )


@pytest.mark.parametrize('arguments', [{'bad': (1, 2)}, {'bad': float('inf')}])
def test_provider_arguments_are_json_values(arguments: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PythonProviderLocation(
            module='show_audio.generators',
            function='tone',
            delivery='buffer',
            arguments=arguments,
        )


def test_provider_arguments_preserve_recursive_json() -> None:
    location = PythonProviderLocation(
        module='show_audio.generators',
        function='tone',
        delivery='client_buffer',
        arguments={'notes': [60, None, {'enabled': True}], 'gain': 0.5},
    )
    assert (
        PythonProviderLocation.model_validate_json(location.model_dump_json())
        == location
    )


@pytest.mark.parametrize(
    'module,function',
    [('show-audio.generators', 'tone'), ('show_audio.generators', 'make.tone')],
)
def test_provider_references_use_python_names(module: str, function: str) -> None:
    with pytest.raises(ValidationError):
        PythonProviderLocation(
            module=module, function=function, delivery='client_buffer'
        )


def test_language_neutral_asset_conformance() -> None:
    cases = json.loads(Path('conformance/assets.json').read_text())
    assert [Asset.model_validate(v).name for v in cases['valid']] == [
        'relative',
        'volume',
        'download',
        'git',
        'radio',
        'generated',
        'input',
        'pull',
    ]
    for value in cases['invalid']:
        with pytest.raises(ValidationError):
            Asset.model_validate(value)


def test_every_location_round_trips_through_toml() -> None:
    cases = json.loads(Path('conformance/assets.json').read_text())
    for asset in cases['valid']:
        score = SlideshowScore.model_validate(
            {
                'name': f'{asset["name"]}-show',
                'title': asset['name'],
                'timebase': {'name': 'seconds', 'rate': {'numerator': 1}},
                'body': {
                    'assets': [asset],
                    'items': [
                        {
                            'name': 'slide',
                            'asset': asset['name'],
                            'duration': 1,
                            'alt': 'Asset location example',
                        }
                    ],
                },
            }
        )
        assert parse_score(score_toml(score)) == score
