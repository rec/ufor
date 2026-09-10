"""In-memory score library resolution. Reading files is an explicit host boundary."""

from collections.abc import Iterator
from enum import StrEnum, auto
from pathlib import PurePosixPath

from pydantic import BaseModel, Field, TypeAdapter

from .base import Model
from .codec import ScoreValue
from .composition import Composition, ScoreRecord
from .interface import InterfaceScore, ScoreVersion
from .preset import PresetScore
from .score import Score
from .selector import (
    Address,
    LibraryName,
    ScoreName,
    ScoreSelector,
    Tags,
    parse_selector,
)


class State(StrEnum):
    pending = auto()
    ready = auto()
    rejected = auto()
    blocked = auto()


class Diagnostic(Model):
    library: str
    address: str
    code: str
    message: str
    field: str | None = None
    cycle: list[str] = Field(default_factory=list)


class Entry(Model):
    library: LibraryName
    address: Address
    name: ScoreName | None = None
    tags: Tags = Field(default_factory=list)
    sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    score: ScoreValue | None = None
    python_class: type[Score] | None = None
    state: State = State.pending
    dependencies: dict[str, str] = Field(default_factory=dict)
    resolved: ScoreValue | None = None
    content_origin: str | None = None

    @property
    def key(self) -> str:
        return f'{self.library}:{self.address}'


class Library:
    """One explicit read's definitions, usable records and recoverable errors."""

    def __init__(
        self, entries: list[Entry], diagnostics: list[Diagnostic] | None = None
    ) -> None:
        self.entries = {e.key: e for e in entries}
        if len(self.entries) != len(entries):
            raise ValueError('duplicate library/address identity')
        self.diagnostics = list(diagnostics or [])
        self.records: dict[str, ScoreRecord] = {}
        self._bind()
        for key in self.entries:
            self._visit(key, [])

    def find(self, selector: str | ScoreSelector = '') -> list[Entry]:
        query = parse_selector(selector) if isinstance(selector, str) else selector
        return [
            e
            for e in self.entries.values()
            if e.state == State.ready
            and query.matches(e.library, e.name, e.tags, e.address)
        ]

    def resolve(self, selector: str | ScoreSelector) -> Entry:
        entry = self._select(selector)
        if entry.state != State.ready:
            raise ValueError(f'{entry.key}: score is {entry.state}')
        return entry

    def composition(
        self, selector: str | ScoreSelector, parameters: dict[str, float] | None = None
    ) -> Composition:
        return Composition(self.resolve(selector).key, self.records, parameters)

    def _select(self, selector: str | ScoreSelector) -> Entry:
        query = parse_selector(selector) if isinstance(selector, str) else selector
        matches = [
            e
            for e in self.entries.values()
            if query.matches(e.library, e.name, e.tags, e.address)
        ]
        if not matches:
            raise ValueError(f'no score matches {str(query)!r}')
        if len(matches) != 1:
            raise ValueError(
                f'ambiguous selector {str(query)!r}: {[e.key for e in matches]}'
            )
        return matches[0]

    def _bind(self) -> None:
        for key, entry in self.entries.items():
            if entry.state != State.pending:
                continue
            if entry.score is None:
                self._fail(key, 'invalid', 'score declaration is missing')
                continue
            dependencies = {}
            for field, reference in references(entry.score):
                try:
                    if reference.selector is not None:
                        target = self._select(reference.selector)
                    else:
                        target_key = relative_key(
                            entry.library, entry.address, str(reference.path)
                        )
                        if target_key not in self.entries:
                            raise ValueError(f'missing score {target_key}')
                        target = self.entries[target_key]
                    if (
                        reference.sha256 is not None
                        and reference.sha256 != target.sha256
                    ):
                        raise ValueError(f'ScoreVersion digest mismatch: {target.key}')
                    dependencies[reference.key] = target.key
                except ValueError as error:
                    self._fail(key, 'reference', str(error), field=field)
                    break
            if self.entries[key].state == State.pending:
                self.entries[key] = entry.model_copy(
                    update={'dependencies': dependencies}
                )

    def _visit(self, key: str, stack: list[str]) -> None:
        entry = self.entries[key]
        if entry.state != State.pending:
            return
        active = [*stack, key]
        assert entry.score is not None
        for field, reference in references(entry.score):
            target = entry.dependencies[reference.key]
            if target in active:
                cycle = [*active[active.index(target) :], target]
                self._fail(
                    key,
                    'cycle',
                    f'circular reference through {reference.key}',
                    field=field,
                    cycle=cycle,
                )
                return
            self._visit(target, active)
            if self.entries[target].state != State.ready:
                self._fail(
                    key,
                    'dependency',
                    f'required score is unavailable: {target}',
                    state=State.blocked,
                    field=field,
                )
                return
        try:
            record, origin = self._normalize(entry)
            if isinstance(record.score, InterfaceScore):
                Composition(key, self.records | {key: record})
        except ValueError as error:
            self._fail(key, 'invalid', str(error))
            return
        self.records[key] = record
        self.entries[key] = entry.model_copy(
            update={
                'state': State.ready,
                'resolved': record.score,
                'content_origin': origin,
            }
        )

    def _normalize(self, entry: Entry) -> tuple[ScoreRecord, str]:
        assert entry.score is not None
        if isinstance(entry.score, PresetScore):
            target = self.entries[entry.dependencies[entry.score.score.key]]
            record = self.records[target.key]
            data = record.score.model_dump()
            if entry.score.parameters:
                if not isinstance(record.score, InterfaceScore):
                    raise ValueError('selected score has no public parameters')
                composition = Composition(target.key, self.records)
                for name, value in entry.score.parameters.items():
                    contract = composition.parameter_contract(target.key, name)
                    if not contract.minimum <= value <= contract.maximum:
                        raise ValueError(
                            f'preset parameter {name} is outside its range'
                        )
                data['parameters'] = [
                    p.model_dump()
                    | (
                        {'default': entry.score.parameters[p.name]}
                        if p.name in entry.score.parameters
                        else {}
                    )
                    for p in record.score.parameters
                ]
            data.update(name=entry.name, title=entry.score.title, tags=entry.tags)
            resolved = TypeAdapter(ScoreValue).validate_python(data)
            assert target.content_origin is not None
            return (
                ScoreRecord(score=resolved, paths=record.paths, sha256=entry.sha256),
                target.content_origin,
            )
        paths = {
            f'dependency_{i}.toml': v for i, v in enumerate(entry.dependencies.values())
        }
        names = {k: f'dependency_{i}.toml' for i, k in enumerate(entry.dependencies)}
        resolved = TypeAdapter(ScoreValue).validate_python(
            normalize_references(entry.score, names)
        )
        return (
            ScoreRecord(score=resolved, paths=paths, sha256=entry.sha256),
            entry.key,
        )

    def _fail(
        self,
        key: str,
        code: str,
        message: str,
        state: State = State.rejected,
        field: str | None = None,
        cycle: list[str] | None = None,
    ) -> None:
        entry = self.entries[key]
        self.entries[key] = entry.model_copy(update={'state': state})
        self.diagnostics.append(
            Diagnostic(
                library=entry.library,
                address=entry.address,
                code=code,
                message=message,
                field=field,
                cycle=cycle or [],
            )
        )


def references(value: object, field: str = '') -> Iterator[tuple[str, ScoreVersion]]:
    if isinstance(value, ScoreVersion):
        yield field, value
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from references(
                getattr(value, name), f'{field}.{name}' if field else name
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from references(item, f'{field}[{index}]')
    elif isinstance(value, dict):
        for name in sorted(value):
            yield from references(value[name], f'{field}[{name}]')


def normalize_references(value: object, names: dict[str, str]) -> object:
    if isinstance(value, ScoreVersion):
        return {'path': names[value.key], 'sha256': value.sha256}
    if isinstance(value, BaseModel):
        return {
            n: normalize_references(getattr(value, n), names)
            for n in type(value).model_fields
        }
    if isinstance(value, list):
        return [normalize_references(v, names) for v in value]
    if isinstance(value, dict):
        return {k: normalize_references(v, names) for k, v in value.items()}
    return value


def relative_key(library: str, address: str, path: str) -> str:
    parts = list(PurePosixPath(address).parent.parts[1:])
    for component in PurePosixPath(path).parts:
        if component == '..':
            if not parts:
                raise ValueError('relative score path escapes its library')
            parts.pop()
        elif component != '.':
            parts.append(component)
    return f'{library}:/{"/".join(parts)}'
