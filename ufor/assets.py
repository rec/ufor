"""Asset identity and locations, without acquiring or loading payloads."""

from keyword import iskeyword
from math import isfinite
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Literal, Self
from urllib.parse import SplitResult, urlsplit

from pydantic import Field, field_validator, model_validator

from .base import Identifier, Model


class RelativeFileLocation(Model):
    kind: Literal['relative_file'] = 'relative_file'
    path: str = Field(min_length=1)

    @field_validator('path')
    @classmethod
    def portable_path(cls, value: str) -> str:
        return _portable_path(value)


class VolumeFileLocation(Model):
    kind: Literal['volume_file'] = 'volume_file'
    volume_id: str = Field(min_length=1)
    volume_name: str | None = Field(default=None, min_length=1)
    path: str = Field(min_length=1)

    @field_validator('path')
    @classmethod
    def portable_path(cls, value: str) -> str:
        return _portable_path(value)


class DownloadLocation(Model):
    kind: Literal['download'] = 'download'
    url: str = Field(min_length=1)

    @field_validator('url')
    @classmethod
    def download_url(cls, value: str) -> str:
        parsed = _absolute_url(value)
        if parsed.scheme != 'https':
            raise ValueError('download URL must use https')
        if parsed.fragment:
            raise ValueError('download URL must not contain a fragment')
        if parsed.username is not None or parsed.password is not None:
            raise ValueError('download URL must not contain credentials')
        return value


class GitFileLocation(Model):
    kind: Literal['git_file'] = 'git_file'
    repository: str = Field(min_length=1)
    commit: str = Field(pattern=r'^(?:[0-9a-f]{40}|[0-9a-f]{64})$')
    path: str = Field(min_length=1)

    @field_validator('repository')
    @classmethod
    def repository_url(cls, value: str) -> str:
        parsed = _absolute_url(value)
        if parsed.scheme not in {
            'git',
            'https',
            'ssh',
        } and not parsed.scheme.startswith('git+'):
            raise ValueError('unsupported Git repository URL scheme')
        if parsed.fragment:
            raise ValueError('Git repository URL must not contain a fragment')
        if parsed.password is not None:
            raise ValueError('Git repository URL must not contain a password')
        return value

    @field_validator('path')
    @classmethod
    def repository_path(cls, value: str) -> str:
        return _portable_path(value)


class StreamLocation(Model):
    kind: Literal['stream'] = 'stream'
    url: str = Field(min_length=1)
    transport: Identifier

    @field_validator('url')
    @classmethod
    def stream_url(cls, value: str) -> str:
        parsed = _absolute_url(value)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError('stream URL must not contain credentials')
        return value


type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)


class PythonProviderLocation(Model):
    kind: Literal['python_provider'] = 'python_provider'
    module: str = Field(min_length=1)
    function: str = Field(min_length=1)
    delivery: Literal['buffer', 'callback', 'client_buffer']
    arguments: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator('module')
    @classmethod
    def module_name(cls, value: str) -> str:
        if any(not _python_identifier(p) for p in value.split('.')):
            raise ValueError('provider module must be a dotted Python name')
        return value

    @field_validator('function')
    @classmethod
    def function_name(cls, value: str) -> str:
        if not _python_identifier(value):
            raise ValueError('provider function must be a Python identifier')
        return value

    @field_validator('arguments', mode='before')
    @classmethod
    def json_arguments(cls, value: object) -> object:
        _validate_json(value)
        if not isinstance(value, dict):
            raise ValueError('provider arguments must be an object')
        return value


AssetLocation = Annotated[
    RelativeFileLocation
    | VolumeFileLocation
    | DownloadLocation
    | GitFileLocation
    | StreamLocation
    | PythonProviderLocation,
    Field(discriminator='kind'),
]


class ContentIdentity(Model):
    byte_length: int = Field(ge=0, strict=True)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class Asset(Model):
    name: Identifier
    location: AssetLocation
    encoding: str = Field(min_length=1)
    content: ContentIdentity | None = None

    @model_validator(mode='after')
    def source_facts(self) -> Self:
        encoded = isinstance(
            self.location,
            RelativeFileLocation
            | VolumeFileLocation
            | DownloadLocation
            | GitFileLocation,
        )
        if encoded != (self.content is not None):
            requirement = 'requires' if encoded else 'must not declare'
            raise ValueError(f'{self.location.kind} {requirement} content identity')
        return self


class AudioDescription(Model):
    timebase: Identifier
    channels: list[str] = Field(min_length=1)
    frames: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode='after')
    def named_channels(self) -> Self:
        if any(not c for c in self.channels):
            raise ValueError('channels must have names')
        if len(self.channels) != len(set(self.channels)):
            raise ValueError('channel names must be unique')
        return self


def finite_audio_required(location: AssetLocation) -> bool:
    return not isinstance(location, StreamLocation) and not (
        isinstance(location, PythonProviderLocation)
        and location.delivery in {'callback', 'client_buffer'}
    )


def _portable_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or PureWindowsPath(value).drive
        or urlsplit(value).scheme
        or '\\' in value
        or any(not p or p in {'.', '..'} for p in value.split('/'))
    ):
        raise ValueError('path must remain inside its declared root')
    return value


def _absolute_url(value: str) -> SplitResult:
    parsed = urlsplit(value)
    if any(c.isspace() for c in value) or not parsed.scheme or not parsed.hostname:
        raise ValueError('URL must be absolute and include a host')
    if parsed.port == 0:
        raise ValueError('URL port must be positive')
    return parsed


def _python_identifier(value: str) -> bool:
    return value.isidentifier() and not iskeyword(value)


def _validate_json(value: object) -> None:
    if value is None or isinstance(value, bool | str) or type(value) is int:
        return
    if type(value) is float:
        if not isfinite(value):
            raise ValueError('provider arguments require finite numbers')
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item)
        return
    if isinstance(value, dict):
        if any(type(k) is not str for k in value):
            raise ValueError('provider argument object keys must be strings')
        for item in value.values():
            _validate_json(item)
        return
    raise ValueError('provider arguments must contain only JSON values')
