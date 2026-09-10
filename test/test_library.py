import json
import shutil
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor import library_files
from ufor.codec import parse_score, score_toml
from ufor.interface import ScoreVersion
from ufor.library import State
from ufor.musical import OscillatorScore
from ufor.oscillator import Oscillator
from ufor.preset import PresetScore
from ufor.selector import (
    LibraryConfig,
    LibraryRegistration,
    ScoreSelector,
    parse_selector,
)

CASES = json.loads(Path('conformance/selectors.json').read_text())
PYTHON = Path('test/fixtures/library_python')


@pytest.mark.parametrize('case', CASES['valid'])
def test_selector_conformance(case: dict[str, object]) -> None:
    selector = parse_selector(case['text'])
    assert str(selector) == case['canonical']
    assert selector.model_dump() == {
        k: v for k, v in case.items() if k not in ('text', 'canonical')
    }
    assert parse_selector(str(selector)) == selector


@pytest.mark.parametrize('text', CASES['invalid'])
def test_malformed_selectors_are_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_selector(text)


def test_selectors_are_literal_and_require_all_parts() -> None:
    selector = parse_selector('library:Pretty score#lake#frogs/bali/frog')
    assert selector.matches(
        'library', 'Pretty score', ['#frogs', '#lake'], '/bali/frog.py'
    )
    assert not selector.matches(
        'library', 'pretty score', ['#frogs', '#lake'], '/bali/frog.py'
    )
    assert not selector.matches('library', 'Pretty score', ['#frogs'], '/bali/frog.py')
    assert not selector.matches(
        'library', 'Pretty score', ['#frogs', '#lake'], '/bali/frogs.py'
    )
    assert parse_selector('a.b').matches('library', 'a.b', [], '/a.toml')
    assert not parse_selector('a.b').matches('library', 'axb', [], '/a.toml')


def test_quotes_and_backslashes_do_not_hide_delimiters() -> None:
    assert parse_selector('"a:b"') == ScoreSelector(library='"a', name='b"')
    assert parse_selector('a\\#b') == ScoreSelector(name='a\\', tags=['#b'])


@pytest.mark.parametrize(
    'values', [{}, {'path': 'a.toml', 'selector': 'a'}, {'selector': 'a:b:c'}]
)
def test_score_version_has_exactly_one_selection(values: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        ScoreVersion.model_validate(values)


def test_selector_versions_and_metadata_round_trip() -> None:
    preset = PresetScore(
        name='quiet frogs',
        title='Quiet frogs',
        tags=['#frogs', '#frogs'],
        score=ScoreVersion(selector='my library: pretty score #lake'),
    )
    assert preset.tags == ['#frogs']
    assert preset.score.selector == 'my library:pretty score#lake'
    assert parse_score(score_toml(preset)) == preset
    assert ScoreVersion(path='a.toml').key != ScoreVersion(selector='a.toml').key


@pytest.mark.parametrize('name', ['a:b', 'a#b', 'a/b', 'a.*b', ' a', 'a '])
def test_reserved_name_characters_are_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        oscillator(name)


def oscillator(name: str = 'triangle') -> OscillatorScore:
    return OscillatorScore(name=name, title=name, body=Oscillator())


def setup_library(tmp_path: Path, name: str = 'local') -> Path:
    config = tmp_path / 'library.toml'
    library_files.create_library(name, Path('scores'), config)
    return config


def save(path: Path, score: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(score_toml(score))


def test_create_and_read_preserve_configuration_and_use_relative_roots(
    tmp_path: Path,
) -> None:
    config = tmp_path / 'nested/library.toml'
    config.parent.mkdir()
    config.write_text('# user comment\n')
    library_files.create_library('local', Path('scores'), config)
    library_files.create_library('second', Path('../second'), config)
    assert '# user comment' in config.read_text()
    assert (tmp_path / 'nested/scores').is_dir()
    assert (tmp_path / 'second').is_dir()
    save(tmp_path / 'nested/scores/z.toml', oscillator('z'))
    save(tmp_path / 'nested/scores/a.toml', oscillator('a'))
    save(tmp_path / 'second/first.toml', oscillator('second'))
    assert [e.name for e in library_files.read_library(config).find()] == [
        'a',
        'z',
        'second',
    ]
    before = config.read_bytes()
    with pytest.raises(ValueError, match='unique'):
        library_files.create_library('local', Path('unused'), config)
    assert config.read_bytes() == before
    assert not (config.parent / 'unused').exists()


def test_default_config_is_optional_and_explicit_config_is_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('HOME', str(tmp_path))
    assert library_files.read_library().find() == []
    assert not (tmp_path / '.config').exists()
    library_files.create_library('default')
    save(tmp_path / '.config/ufor/scores/default.toml', oscillator('default'))
    local = setup_library(tmp_path)
    save(tmp_path / 'scores/local.toml', oscillator('local'))
    assert [e.name for e in library_files.read_library().find()] == ['default']
    assert [e.name for e in library_files.read_library(local).find()] == ['local']
    with pytest.raises(FileNotFoundError):
        library_files.read_library(tmp_path / 'missing.toml')


def test_cycle_rejects_the_closing_score_and_blocks_dependents(tmp_path: Path) -> None:
    config = setup_library(tmp_path)
    for name, target in [('a', 'b'), ('b', 'c'), ('c', 'a')]:
        save(
            tmp_path / f'scores/{name}.toml',
            PresetScore(name=name, title=name, score=ScoreVersion(selector=target)),
        )
    save(tmp_path / 'scores/good.toml', oscillator('good'))
    result = library_files.read_library(config)
    assert [e.name for e in result.find()] == ['good']
    assert result.entries['local:/c.toml'].state == State.rejected
    assert result.entries['local:/a.toml'].state == State.blocked
    assert result.entries['local:/b.toml'].state == State.blocked
    cycles = [d for d in result.diagnostics if d.code == 'cycle']
    assert len(cycles) == 1
    assert cycles[0].cycle == [
        'local:/a.toml',
        'local:/b.toml',
        'local:/c.toml',
        'local:/a.toml',
    ]
    assert cycles[0].field == 'score'
    save(tmp_path / 'scores/c.toml', oscillator('c'))
    assert len(library_files.read_library(config).find()) == 4


def test_forward_references_and_nonplayable_presets(tmp_path: Path) -> None:
    config = setup_library(tmp_path)
    save(
        tmp_path / 'scores/a.toml',
        PresetScore(
            name='first',
            title='First',
            tags=['#preset'],
            score=ScoreVersion(selector='second'),
        ),
    )
    save(
        tmp_path / 'scores/b.toml',
        PresetScore(
            name='second', title='Second', score=ScoreVersion(path='nested/osc.toml')
        ),
    )
    save(tmp_path / 'scores/nested/osc.toml', oscillator('original'))
    result = library_files.read_library(config)
    first = result.resolve('first')
    assert isinstance(first.resolved, OscillatorScore)
    assert first.resolved.name == 'first'
    assert first.resolved.tags == ['#preset']
    assert first.content_origin == 'local:/nested/osc.toml'
    assert first.resolved.body == result.resolve('original').resolved.body
    with pytest.raises(ValueError, match='cannot be instantiated'):
        result.composition('first')


def test_ambiguity_does_not_fall_back_after_a_body_is_rejected(tmp_path: Path) -> None:
    config = setup_library(tmp_path)
    save(tmp_path / 'scores/good.toml', oscillator('same'))
    invalid = oscillator('same').model_dump(mode='json') | {'kind': 'unknown'}
    import tomlkit

    (tmp_path / 'scores/bad.toml').write_text(tomlkit.dumps(invalid))
    save(
        tmp_path / 'scores/ref.toml',
        PresetScore(name='ref', title='Ref', score=ScoreVersion(selector='same')),
    )
    result = library_files.read_library(config)
    assert len(result.find('same')) == 1
    with pytest.raises(ValueError, match='ambiguous'):
        result.resolve('same')
    assert result.entries['local:/ref.toml'].state == State.rejected


def test_extensionless_address_reserves_failed_python_candidates(
    tmp_path: Path,
) -> None:
    config = setup_library(tmp_path)
    save(tmp_path / 'scores/same.toml', oscillator())
    shutil.copyfile(PYTHON / 'syntax.txt', tmp_path / 'scores/same.py')
    result = library_files.read_library(config)
    with pytest.raises(ValueError, match='ambiguous'):
        result.resolve('/same')
    assert result.resolve('/same.toml').name == 'triangle'


def test_python_classes_are_retained_without_construction_or_module_collisions(
    tmp_path: Path,
) -> None:
    config = setup_library(tmp_path)
    for directory in ('a', 'b'):
        target = tmp_path / f'scores/{directory}/oscillator.py'
        target.parent.mkdir()
        shutil.copyfile(PYTHON / 'oscillator.py', target)
    modules = set(sys.modules)
    result = library_files.read_library(config)
    entries = result.find('#python')
    assert len(entries) == 2
    assert entries[0].python_class is not entries[1].python_class
    assert entries[0].python_class.__module__ != entries[1].python_class.__module__
    assert all(isinstance(e.resolved, OscillatorScore) for e in entries)
    assert not list(tmp_path.rglob('__pycache__'))
    assert not [m for m in set(sys.modules) - modules if m.startswith('_ufor_score_')]


@pytest.mark.parametrize(
    'fixture', ['import_failure.py', 'imported_only.py', 'multiple.py', 'syntax.txt']
)
def test_python_failure_does_not_stop_other_entries(
    tmp_path: Path, fixture: str
) -> None:
    config = setup_library(tmp_path)
    shutil.copyfile(PYTHON / fixture, tmp_path / 'scores/bad.py')
    save(tmp_path / 'scores/good.toml', oscillator('good'))
    result = library_files.read_library(config)
    assert [e.name for e in result.find()] == ['good']
    assert result.diagnostics[0].address == '/bad.py'


def test_python_preset_declares_dependencies_and_preserves_implementation(
    tmp_path: Path,
) -> None:
    config = setup_library(tmp_path)
    shutil.copyfile(PYTHON / 'preset.py', tmp_path / 'scores/a.py')
    shutil.copyfile(PYTHON / 'oscillator.py', tmp_path / 'scores/z.py')
    result = library_files.read_library(config)
    assert (
        result.resolve('Python preset').python_class
        is not result.resolve('Python triangle').python_class
    )
    assert result.resolve('Python preset').python_class.__name__ == 'LocalPreset'
    assert result.resolve('Python preset').content_origin == 'local:/z.py'


def test_user_interrupt_is_not_swallowed(tmp_path: Path) -> None:
    config = setup_library(tmp_path)
    shutil.copyfile(PYTHON / 'interrupt.py', tmp_path / 'scores/interrupt.py')
    with pytest.raises(KeyboardInterrupt):
        library_files.read_library(config)


def test_hashes_apply_to_exact_selected_file_bytes(tmp_path: Path) -> None:
    config = setup_library(tmp_path)
    file = tmp_path / 'scores/source.toml'
    save(file, oscillator())
    pin = sha256(file.read_bytes()).hexdigest()
    save(
        tmp_path / 'scores/preset.toml',
        PresetScore(
            name='pinned',
            title='Pinned',
            score=ScoreVersion(selector='triangle', sha256=pin),
        ),
    )
    assert library_files.read_library(config).resolve('pinned').state == State.ready
    file.write_text(file.read_text() + '\n')
    result = library_files.read_library(config)
    assert result.entries['local:/preset.toml'].state == State.rejected
    assert any('digest mismatch' in d.message for d in result.diagnostics)


def test_symlinks_and_unreadable_roots_do_not_stop_good_roots(tmp_path: Path) -> None:
    config = setup_library(tmp_path)
    save(tmp_path / 'scores/good.toml', oscillator('good'))
    (tmp_path / 'scores/link.toml').symlink_to(tmp_path / 'scores/good.toml')
    (tmp_path / 'scores/loop').symlink_to(tmp_path / 'scores', target_is_directory=True)
    import tomlkit

    config.write_text(
        tomlkit.dumps(
            LibraryConfig(
                libraries=[
                    LibraryRegistration(name='missing', root='absent'),
                    LibraryRegistration(name='local', root='scores'),
                ]
            ).model_dump()
        )
    )
    result = library_files.read_library(config)
    assert [e.name for e in result.find()] == ['good']
    assert [d.code for d in result.diagnostics].count('symlink') == 2
    assert any(d.code == 'io' for d in result.diagnostics)


def test_relative_references_cannot_escape_the_library(tmp_path: Path) -> None:
    config = setup_library(tmp_path)
    save(
        tmp_path / 'scores/preset.toml',
        PresetScore(
            name='escape', title='Escape', score=ScoreVersion(path='../outside.toml')
        ),
    )
    result = library_files.read_library(config)
    assert result.entries['local:/preset.toml'].state == State.rejected
    assert 'escapes its library' in result.diagnostics[0].message


def test_example_library_presets_composition_and_nonplayable_scores() -> None:
    result = library_files.read_library(Path('conformance/library/library.toml'))
    assert not result.diagnostics
    expected = json.loads(Path('conformance/library/expected.json').read_text())
    assert [
        {'name': e.name, 'address': e.address, 'tags': e.tags} for e in result.find()
    ] == expected
    assert (
        result.resolve('my library: pretty score #frogs #lake /pretty').address
        == '/pretty.toml'
    )
    for name, default in [
        ('pretty score', 1),
        ('quiet frogs', 0.25),
        ('half frogs', 0.5),
    ]:
        assert result.composition(name).parts['root'].parameters == {
            'brightness': default
        }
    root = 'root'
    assert result.composition('half frogs', {'brightness': 0.75}).parts[
        root
    ].parameters == {'brightness': 0.75}
    pond = result.composition('pond')
    assert pond.parts['root/left'].parameters == {'brightness': 0.25}
    assert pond.parts['root/right'].parameters == {'brightness': 0.5}
    assert result.resolve('western').resolved.kind == 'tuning'
    assert result.resolve('half frogs').content_origin == 'my library:/pretty.toml'


@pytest.mark.parametrize('parameters', [{'missing': 1}, {'brightness': 3}])
def test_invalid_preset_settings_reject_only_affected_scores(
    tmp_path: Path, parameters: dict[str, float]
) -> None:
    shutil.copytree('conformance/library', tmp_path / 'library')
    file = tmp_path / 'library/scores/quiet.toml'
    score = parse_score(file.read_text())
    save(file, score.model_copy(update={'parameters': parameters}))
    result = library_files.read_library(tmp_path / 'library/library.toml')
    assert result.entries['my library:/quiet.toml'].state == State.rejected
    assert result.entries['my library:/half.toml'].state == State.blocked
    assert result.resolve('pretty score').state == State.ready


def test_cross_library_cycles_and_unqualified_ambiguity(tmp_path: Path) -> None:
    config = setup_library(tmp_path, 'first')
    (tmp_path / 'other').mkdir()
    config.write_text(
        config.read_text() + '\n[[libraries]]\nname = "second"\nroot = "other"\n'
    )
    save(
        tmp_path / 'scores/a.toml',
        PresetScore(name='a', title='A', score=ScoreVersion(selector='second:b')),
    )
    save(
        tmp_path / 'other/b.toml',
        PresetScore(name='b', title='B', score=ScoreVersion(selector='first:a')),
    )
    save(tmp_path / 'scores/one.toml', oscillator())
    save(tmp_path / 'other/two.toml', oscillator())
    save(
        tmp_path / 'scores/ambiguous.toml',
        PresetScore(
            name='ambiguous', title='Ambiguous', score=ScoreVersion(selector='triangle')
        ),
    )
    result = library_files.read_library(config)
    assert result.entries['second:/b.toml'].state == State.rejected
    assert result.entries['first:/a.toml'].state == State.blocked
    assert result.entries['first:/ambiguous.toml'].state == State.rejected
    assert next(d.cycle for d in result.diagnostics if d.code == 'cycle') == [
        'first:/a.toml',
        'second:/b.toml',
        'first:/a.toml',
    ]
    assert len(result.find('triangle')) == 2


@pytest.mark.parametrize('selector, code', [('self', 'cycle'), ('absent', 'reference')])
def test_self_reference_and_missing_dependency(
    tmp_path: Path, selector: str, code: str
) -> None:
    config = setup_library(tmp_path)
    save(
        tmp_path / 'scores/self.toml',
        PresetScore(name='self', title='Self', score=ScoreVersion(selector=selector)),
    )
    result = library_files.read_library(config)
    assert result.entries['local:/self.toml'].state == State.rejected
    assert result.diagnostics[0].code == code


def test_config_inside_root_is_not_a_score(tmp_path: Path) -> None:
    config = tmp_path / 'library.toml'
    config.write_text('[[libraries]]\nname = "local"\nroot = "."\n')
    save(tmp_path / 'tone.toml', oscillator())
    result = library_files.read_library(config)
    assert not result.diagnostics
    assert len(result.find()) == 1


def test_root_permission_failure_is_reported_and_other_roots_continue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = setup_library(tmp_path)
    save(tmp_path / 'scores/tone.toml', oscillator())
    config.write_text(
        '[[libraries]]\nname = "denied"\nroot = "denied"\n' + config.read_text()
    )
    is_dir = Path.is_dir

    def directory(path: Path) -> bool:
        if path == tmp_path / 'denied':
            raise PermissionError('denied root')
        return is_dir(path)

    monkeypatch.setattr(Path, 'is_dir', directory)
    result = library_files.read_library(config)
    assert result.resolve('triangle').state == State.ready
    assert result.diagnostics[0].code == 'io'


def test_config_with_parent_components_is_excluded(tmp_path: Path) -> None:
    (tmp_path / 'nested').mkdir()
    config = tmp_path / 'library.toml'
    config.write_text('[[libraries]]\nname = "local"\nroot = "."\n')
    assert not library_files.read_library(tmp_path / 'nested/../library.toml').entries
