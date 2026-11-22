"""Verify the settings body and authored target contract in both formats."""

import json
from pathlib import Path

import pytest

from ufor.codec import parse_sound_settings, sound_settings_text
from ufor.modulation import Target
from ufor.samples.controls import ControlDeclaration
from ufor.samples.processing import (
    ResolvedTarget,
    ResonantFilter,
    SoundSettings,
    biquad_coefficients,
)

CORPUS = Path(__file__).resolve().parents[1] / 'conformance'
CASES = json.loads((CORPUS / 'sound-settings.json').read_text())


@pytest.mark.parametrize(
    'case', json.loads((CORPUS / 'filter-cutoff.json').read_text())
)
def test_biquad_respects_authored_cutoff_policy(case: dict) -> None:
    definition = ResonantFilter.model_validate(
        dict(
            name='tone',
            response=case['response'],
            cutoff_hz=case['cutoff'],
            q=1.0,
            nyquist_ratio=0.5,
            boundary=case['boundary'],
        )
    )
    rate = case['rate']
    if 'bounds' in case:
        assert list(definition.cutoff_bounds(rate)) == case['bounds']
    else:
        with pytest.raises(ValueError):
            definition.cutoff_bounds(rate)
    if 'coefficients' in case:
        coefficients = biquad_coefficients(definition, rate)
        assert list(coefficients.model_dump().values()) == pytest.approx(
            case['coefficients'], abs=1e-14
        )
    else:
        with pytest.raises(ValueError):
            biquad_coefficients(definition, rate)


@pytest.mark.parametrize('case', CASES['rejected'], ids=lambda c: c['id'])
def test_invalid_portable_settings(case: dict) -> None:
    with pytest.raises(ValueError):
        parse_sound_settings(json.dumps(case['input']), 'json')


@pytest.mark.parametrize('case', CASES['accepted'], ids=lambda c: c['id'])
def test_portable_settings_and_context(case: dict) -> None:
    authored = case['input']
    text = json.dumps(authored)
    settings = parse_sound_settings(text, 'json')
    if 'records' in case:
        count = case['records']
        bounded = parse_sound_settings(text, 'json', max_records=count)
        encoded = sound_settings_text(bounded, 'json', max_records=count)
        parse_sound_settings(encoded, 'json', max_records=count)
        with pytest.raises(ValueError):
            parse_sound_settings(text, 'json', max_records=count - 1)
    checks = settings.validate_context()
    assert [b.control for b in settings.bindings if b.kind == 'control'] == (
        checks.unresolved_controls
    )
    assert checks.unresolved_controls == case.get('unresolved_controls', [])
    assert [[t.name, t.parameter] for t in checks.unresolved_targets] == case.get(
        'unresolved_targets', []
    )
    if checks.unresolved_controls or checks.unresolved_targets:
        with pytest.raises(ValueError):
            checks.require_complete()
    else:
        checks.require_complete()
    if 'controls' in case:
        controls = {
            n: ControlDeclaration.model_validate(v) for n, v in case['controls'].items()
        }
        wrong = {
            n: ControlDeclaration.model_validate(v)
            for n, v in case['wrong_controls'].items()
        }
        settings.validate_context(controls).require_complete()
        for supplied in ({}, wrong):
            with pytest.raises(ValueError):
                settings.validate_context(supplied)
        with pytest.raises(ValueError):
            settings.validate_context(controls, max_records=case['records'])
        settings.validate_context(
            controls, max_records=case['records'] + 1
        ).require_complete()
    if 'materialized' in case:
        concrete = authored | {'envelfos': case['materialized']}
        parse_sound_settings(
            json.dumps(concrete), 'json'
        ).validate_context().require_complete()
        with pytest.raises(ValueError):
            parse_sound_settings(
                json.dumps(authored | {'envelfos': case['incompatible']}), 'json'
            )
    restored = parse_sound_settings(sound_settings_text(settings, 'toml'), 'toml')
    assert (
        parse_sound_settings(
            sound_settings_text(settings, 'json'), 'json'
        ).validate_context()
        == checks
    )
    assert restored.validate_context() == checks
    assert restored.processing == settings.processing
    assert restored.modulation == settings.modulation
    for value in (settings, restored):
        if 'filter_order' in case:
            assert [f.name for f in value.processing.filters] == case['filter_order']
        if 'generator_order' in case:
            assert list(value.envelfos) == case['generator_order']
        for name, parameter, unit, default, *timing in case.get('targets', []):
            resolved = value.resolve_target(Target(name=name, parameter=parameter))
            assert isinstance(resolved, ResolvedTarget)
            assert (resolved.unit, resolved.default_value) == (unit, default)
            duration = str(resolved.duration) if resolved.duration is not None else None
            assert (duration, resolved.scope) == tuple(timing or (None, None))
        for name, parameter in case.get('unknown', []):
            with pytest.raises(ValueError):
                value.resolve_target(Target(name=name, parameter=parameter))


def test_toml_keeps_authored_generator_order() -> None:
    settings = parse_sound_settings(
        (CORPUS / 'sound-settings-order.toml').read_text(), 'toml'
    )
    assert list(settings.envelfos) == ['z-beat', 'a-held']


def test_portable_validation_rechecks_existing_settings() -> None:
    settings = SoundSettings()
    settings.processing.filters.extend([object()])  # type: ignore[list-item]
    with pytest.raises(ValueError):
        SoundSettings.model_validate(settings, context={'portable': True})


def test_large_settings_use_one_configurable_budget() -> None:
    budget = CASES['budget']
    data = {
        'processing': {
            'equalizer': [
                {'name': f'band-{i}', 'frequency_hz': 20, 'gain_db': 0, 'resonance': 1}
                for i in range(budget['band_count'])
            ]
        }
    }
    text = json.dumps(data)
    with pytest.raises(ValueError):
        parse_sound_settings(text, 'json')
    settings = parse_sound_settings(text, 'json', max_records=budget['records'])
    settings.validate_context(max_records=budget['records']).require_complete()
    assert len(settings.processing.equalizer) == budget['band_count']
