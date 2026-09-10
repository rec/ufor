"""Literal score selectors, with reserved delimiters and no quoting syntax."""

from typing import Annotated

from pydantic import AfterValidator, Field, field_validator

from .base import Model


def library_name(value: str) -> str:
    if not value or value != value.strip() or any(c in value for c in ':#/'):
        raise ValueError('library names must be nonempty, trimmed and contain no : # /')
    return value


def score_name(value: str) -> str:
    library_name(value)
    if '.*' in value:
        raise ValueError('score names must not contain .*')
    return value


def tag(value: str) -> str:
    if not value.startswith('#') or len(value) == 1:
        raise ValueError('tags require # followed by a nonempty value')
    if any(c.isspace() or c in ':#/' for c in value[1:]):
        raise ValueError('tag values must contain no whitespace or : # /')
    return value


def address(value: str) -> str:
    if not value.startswith('/') or any(c in value for c in ':#\\'):
        raise ValueError('addresses require / and cannot contain : # or backslashes')
    if any(p in ('', '.', '..') or p != p.strip() for p in value[1:].split('/')):
        raise ValueError('address components must be nonempty, trimmed and not . or ..')
    return value


def distinct_tags(value: list[str]) -> list[str]:
    return list(dict.fromkeys(value))


LibraryName = Annotated[str, AfterValidator(library_name)]
ScoreName = Annotated[str, AfterValidator(score_name)]
Tag = Annotated[str, AfterValidator(tag)]
Tags = Annotated[list[Tag], AfterValidator(distinct_tags)]
Address = Annotated[str, AfterValidator(address)]


class ScoreSelector(Model):
    library: LibraryName | None = None
    name: ScoreName | None = None
    tags: Tags = Field(default_factory=list)
    address: Address | None = None

    def __str__(self) -> str:
        return (
            (f'{self.library}:' if self.library is not None else '')
            + (self.name or '')
            + ''.join(self.tags)
            + (self.address or '')
        )

    def matches(
        self, library: str, name: str | None, tags: list[str], address: str
    ) -> bool:
        if self.library is not None and self.library != library:
            return False
        if self.name is not None and self.name != name:
            return False
        if not set(self.tags) <= set(tags):
            return False
        if self.address is None:
            return True
        if self.address.endswith(('.toml', '.py')):
            return self.address == address
        return address in (self.address + '.toml', self.address + '.py')


def parse_selector(text: str) -> ScoreSelector:
    rest = text.strip()
    library = None
    if ':' in rest:
        prefix, rest = rest.split(':', 1)
        library = library_name(prefix.strip())
    path = None
    if '/' in rest:
        rest, path = rest.split('/', 1)
        path = address('/' + path.strip())
    words = rest.split('#')
    name = words[0].strip() or None
    tags = [tag('#' + w.strip()) for w in words[1:]]
    return ScoreSelector(library=library, name=name, tags=tags, address=path)


class LibraryRegistration(Model):
    name: LibraryName
    root: str = Field(min_length=1)


class LibraryConfig(Model):
    libraries: list[LibraryRegistration] = Field(default_factory=list)

    @field_validator('libraries')
    @classmethod
    def unique_names(
        cls, value: list[LibraryRegistration]
    ) -> list[LibraryRegistration]:
        if len({r.name for r in value}) != len(value):
            raise ValueError('library names must be unique')
        return value
