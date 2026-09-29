"""Explicit filesystem and local Python loading for user score libraries."""

import fcntl
import os
import sys
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from os.path import abspath
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

import tomlkit
from pydantic import TypeAdapter

from .library import Diagnostic, Entry, Library, State
from .score import Score
from .score_types import ScoreValue
from .selector import LibraryConfig, LibraryRegistration, address


def read_library(config_path: Path | None = None, max_depth: int = 128) -> Library:
    path = configuration_path(config_path)
    if config_path is None and not path.exists():
        return Library([], max_depth=max_depth)
    config = LibraryConfig.model_validate(tomlkit.parse(path.read_text()))
    entries = []
    diagnostics = []
    for registration in config.libraries:
        root = expanded_path(registration.root)
        if not root.is_absolute():
            root = path.parent / root
        root = Path(abspath(root))
        try:
            symlink = root.is_symlink()
            directory = root.is_dir()
        except OSError as error:
            diagnostics.append(
                Diagnostic(
                    library=registration.name,
                    address='/',
                    code='io',
                    message=str(error),
                )
            )
            continue
        if symlink:
            diagnostics.append(
                Diagnostic(
                    library=registration.name,
                    address='/',
                    code='symlink',
                    message='symlinked library root skipped',
                )
            )
            continue
        if not directory:
            diagnostics.append(
                Diagnostic(
                    library=registration.name,
                    address='/',
                    code='io',
                    message=f'library root is not a directory: {root}',
                )
            )
            continue
        for file in score_files(root, path, registration.name, diagnostics):
            location = '/' + file.relative_to(root).as_posix()
            entry = None
            try:
                address(location)
                entry = Entry(library=registration.name, address=location)
                contents = file.read_bytes()
                entry = entry.model_copy(
                    update={'sha256': sha256(contents).hexdigest()}
                )
                score_class = None
                if file.suffix == '.py':
                    score_class, data = python_score(
                        file, registration.name, location, contents
                    )
                else:
                    data = dict(tomlkit.parse(contents.decode('utf-8')))
                entry = Entry.model_validate(
                    entry.model_dump()
                    | {
                        'name': data.get('name'),
                        'tags': data.get('tags', []),
                        'python_class': score_class,
                    }
                )
            except (Exception, SystemExit) as error:
                # User modules and their defaults can raise arbitrary exceptions.
                # This boundary isolates one file; KeyboardInterrupt still propagates.
                diagnostics.append(
                    Diagnostic(
                        library=registration.name,
                        address=location,
                        code='python' if file.suffix == '.py' else 'invalid',
                        message=f'{type(error).__name__}: {error}',
                    )
                )
                if entry is not None:
                    entries.append(entry.model_copy(update={'state': State.rejected}))
                continue
            try:
                score = TypeAdapter(ScoreValue).validate_python(data)
            except ValueError as error:
                # Keep valid metadata in the index even when the body is invalid.
                # Otherwise an ambiguous selector could silently fall back.
                entry = entry.model_copy(update={'state': State.rejected})
                diagnostics.append(
                    Diagnostic(
                        library=registration.name,
                        address=location,
                        code='invalid',
                        message=str(error),
                    )
                )
            else:
                entry = entry.model_copy(update={'score': score})
            entries.append(entry)
    return Library(entries, diagnostics, max_depth=max_depth)


def create_library(
    name: str, root: Path | None = None, config_path: Path | None = None
) -> LibraryConfig:
    path = configuration_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f'{path.name}.lock')
    with lock_path.open('a+b') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        document = (
            tomlkit.parse(path.read_text()) if path.exists() else tomlkit.document()
        )
        config = LibraryConfig.model_validate(document)
        selected = (
            expanded_path(str(root))
            if root is not None
            else Path.home() / '.config/ufor/scores'
        )
        registration = LibraryRegistration(name=name, root=str(selected))
        updated = LibraryConfig(libraries=[*config.libraries, registration])
        directory = selected if selected.is_absolute() else path.parent / selected
        if directory.is_symlink():
            raise ValueError('library root must not be a symlink')
        directory.mkdir(parents=True, exist_ok=True)
        if 'libraries' not in document:
            document['libraries'] = tomlkit.aot()
        table = tomlkit.table()
        table.update(registration.model_dump())
        document['libraries'].append(table)
        _write_config(path, tomlkit.dumps(document))
        return updated


def _write_config(path: Path, contents: str) -> None:
    temporary = NamedTemporaryFile(
        mode='w', dir=path.parent, prefix=f'.{path.name}.', delete=False
    )
    temporary_path = Path(temporary.name)
    try:
        with temporary:
            temporary.write(contents)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def score_files(
    root: Path, config: Path, library: str, diagnostics: list[Diagnostic]
) -> list[Path]:
    files = []

    def walk_error(error: OSError) -> None:
        diagnostics.append(
            Diagnostic(library=library, address='/', code='io', message=str(error))
        )

    for directory, folders, names in root.walk(
        on_error=walk_error, follow_symlinks=False
    ):
        for name in [*folders, *names]:
            file = directory / name
            try:
                symlink = file.is_symlink()
            except OSError as error:
                diagnostics.append(
                    Diagnostic(
                        library=library,
                        address='/' + file.relative_to(root).as_posix(),
                        code='io',
                        message=str(error),
                    )
                )
                continue
            if symlink:
                diagnostics.append(
                    Diagnostic(
                        library=library,
                        address='/' + file.relative_to(root).as_posix(),
                        code='symlink',
                        message='symlink skipped',
                    )
                )
            elif (
                name in names
                and file.suffix in ('.toml', '.py')
                and file.absolute() != config
            ):
                files.append(file)
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def python_score(
    path: Path, library: str, location: str, contents: bytes
) -> tuple[type[Score], dict[str, object]]:
    identity = f'{library}:{location}:{path}'
    name = '_ufor_score_' + sha256(identity.encode()).hexdigest() + '_' + uuid4().hex
    spec = spec_from_file_location(name, path)
    if spec is None:
        raise ValueError('cannot create module specification')
    module = module_from_spec(spec)
    sys.modules[name] = module
    try:
        # Compile the bytes already hashed, and never write a __pycache__ directory.
        exec(compile(contents, str(path), 'exec'), module.__dict__)
        classes = list(
            dict.fromkeys(
                v
                for v in vars(module).values()
                if isinstance(v, type) and issubclass(v, Score) and v.__module__ == name
            )
        )
        if len(classes) != 1:
            raise ValueError('Python file must define exactly one local Score subclass')
        score_class = classes[0]
        data = {}
        for field, definition in score_class.model_fields.items():
            if not definition.is_required():
                data[field] = definition.get_default(
                    call_default_factory=True, validated_data=data
                )
        return score_class, data
    finally:
        # Retained classes keep their method globals; do not accumulate modules.
        sys.modules.pop(name, None)


def configuration_path(path: Path | None) -> Path:
    selected = (
        expanded_path(str(path))
        if path is not None
        else Path.home() / '.config/ufor/library.toml'
    )
    return Path(abspath(selected))


def expanded_path(value: str) -> Path:
    return Path.home() / value[2:] if value.startswith('~/') else Path(value)
