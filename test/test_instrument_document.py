import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor import envelope, segments
from ufor.base import Model
from ufor.codec import migrate_score_v3, parse_score, score_schema, score_toml
from ufor.interface import ScoreReference
from ufor.library import Entry, Library
from ufor.preset import PresetScore
from ufor.samples import playback, processing, selection
from ufor.samples.controls import ControlDeclaration
from ufor.samples.instrument import (
    SampleInstrumentScore,
    SampleSettings,
    effective_selection,
    effective_settings,
)


def test_native_instrument_round_trips_through_the_common_codec() -> None:
    document = SampleInstrumentScore.model_validate(fixture())
    assert parse_score(score_toml(document)) == document
    assert (
        SampleInstrumentScore.model_validate_json(document.model_dump_json())
        == document
    )
    assert json.loads(Path('schema/scores.json').read_text()) == score_schema()
    assert document.body.slots[0].envelope.segments[1].duration == Fraction(1, 100)
    assert document.assets[0].audio.timebase == 'native-44100'
    assert document.outputs[0].stream.timebase == 'output'
    assert document.body.slices[0].end_frame == 1000


def test_version_three_assets_migrate_without_compatibility_fields() -> None:
    current = fixture()
    previous = deepcopy(current)
    previous['version'] = 3
    asset = previous['assets'][0]
    asset['path'] = asset.pop('location')['path']
    content = asset.pop('content')
    asset.update(content)

    assert migrate_score_v3(previous) == SampleInstrumentScore.model_validate(current)
    assert previous['version'] == 3
    with pytest.raises(ValidationError):
        SampleInstrumentScore.model_validate(previous)


def test_voice_policy_round_trips_through_toml() -> None:
    raw = fixture()
    raw['body']['settings']['voice_policy'] = {
        'maximum_voices': 16,
        'same_key': 'release',
        'overflow': 'replace_oldest',
    }
    document = SampleInstrumentScore.model_validate(raw)
    assert parse_score(score_toml(document)) == document


def test_voice_pool_round_trips_through_toml() -> None:
    raw = fixture()
    raw['body']['voice_pools'] = [{'name': 'drums', 'policy': {'maximum_voices': 2}}]
    raw['body']['slots'][0]['voice_pool'] = 'drums'
    document = SampleInstrumentScore.model_validate(raw)

    assert parse_score(score_toml(document)) == document


def test_end_fade_round_trips_through_toml() -> None:
    raw = fixture()
    raw['body']['slots'][0]['playback']['end_fade_seconds'] = 0.25

    document = SampleInstrumentScore.model_validate(raw)

    assert parse_score(score_toml(document)) == document


@pytest.mark.parametrize('repetition', ['loop', 'play_count'])
def test_end_fade_rejects_undefined_repetition(repetition: str) -> None:
    raw = fixture()
    raw['body']['slots'][0]['playback']['end_fade_seconds'] = 0.25
    if repetition == 'loop':
        raw['body']['slices'][0]['loop'] = {
            'start_frame': 100,
            'end_frame': 200,
        }
    else:
        raw['body']['slots'][0]['playback'].update(
            {'mode': 'one_shot', 'play_count': 2}
        )

    with pytest.raises(ValidationError, match='end fade requires unlooped'):
        SampleInstrumentScore.model_validate(raw)


def test_instrument_score_tags_use_the_library_contract() -> None:
    raw = fixture()
    raw['tags'] = ['#sample', '#sample']
    document = SampleInstrumentScore.model_validate(raw)
    assert document.tags == ['#sample']
    library = Library(
        [
            Entry(
                library='test',
                address='/glass.toml',
                name=document.name,
                tags=document.tags,
                score=document,
            )
        ]
    )
    assert library.resolve('#sample').resolved.tags == ['#sample']
    raw['tags'] = ['sample']
    with pytest.raises(ValueError, match='tags require #'):
        SampleInstrumentScore.model_validate(raw)


@pytest.mark.parametrize('boundary', ['json', 'toml', 'library', 'preset'])
@pytest.mark.parametrize('override', [False, True])
def test_group_processing_survives_interchange(boundary: str, override: bool) -> None:
    raw = fixture()
    raw['body']['groups'] = [{'name': 'quiet', 'processing': {'volume_db': -6}}]
    raw['body']['slots'][0].pop('processing', None)
    raw['body']['slots'][0]['group'] = 'quiet'
    if override:
        raw['body']['slots'][0]['processing'] = {'volume_db': 0}
    document = SampleInstrumentScore.model_validate(raw)
    if boundary == 'json':
        restored = SampleInstrumentScore.model_validate_json(document.model_dump_json())
    elif boundary == 'toml':
        restored = parse_score(score_toml(document))
    else:
        preset = PresetScore(
            name='preset', title='Preset', score=ScoreReference(path='glass.toml')
        )
        library = Library(
            [
                Entry(
                    library='test', address='/glass.toml', name='glass', score=document
                ),
                Entry(
                    library='test', address='/preset.toml', name='preset', score=preset
                ),
            ]
        )
        restored = library.resolve(
            'preset' if boundary == 'preset' else 'glass'
        ).resolved
    assert isinstance(restored, SampleInstrumentScore)
    assert effective_settings(
        restored.body.slots[0], restored.body.groups[0]
    ).processing.volume_db == (0 if override else -6)


def test_documented_native_example_is_complete() -> None:
    text = (
        Path('doc/instrument-format.md')
        .read_text()
        .split('```toml\n', 1)[1]
        .split('```', 1)[0]
    )
    document = parse_score(text)
    assert isinstance(document, SampleInstrumentScore)
    assert parse_score(score_toml(document)) == document


@pytest.mark.parametrize(
    'selection_value,expected', [(None, 'takes'), (False, None), ('other', 'other')]
)
def test_group_selection_and_empty_envelope_survive_toml(
    selection_value: str | bool | None, expected: str | None
) -> None:
    raw = fixture()
    raw['body']['settings']['selections'] = [
        {'name': n, 'mode': 'cycle'} for n in ('takes', 'other')
    ]
    raw['body']['groups'] = [
        {
            'name': 'group',
            'selection': 'takes',
            'envelope': raw['body']['slots'][0]['envelope'],
        }
    ]
    raw['body']['slots'][0].update(
        group='group', selection=selection_value, envelope=None
    )
    document = SampleInstrumentScore.model_validate(raw)
    for restored in (
        parse_score(score_toml(document)),
        SampleInstrumentScore.model_validate_json(document.model_dump_json()),
    ):
        assert isinstance(restored, SampleInstrumentScore)
        slot, group = restored.body.slots[0], restored.body.groups[0]
        assert effective_selection(slot, group) == expected
        assert effective_settings(slot, group).envelope is None


@pytest.mark.parametrize('version', [True, 3, 4.0, '4', 1])
def test_instrument_version_requires_integer_four(version: object) -> None:
    with pytest.raises(ValidationError):
        SampleInstrumentScore.model_validate(fixture() | {'version': version})


def test_whole_envelope_overrides_and_playback_inheritance_round_trip() -> None:
    raw = fixture()
    raw['body']['settings']['playback'] = {
        'direction': 'backward',
        'mode': 'one_shot',
    }
    raw['body']['settings']['envelope'] = envelope.Envelope(
        segments=[segments.Segment(duration=1, to=1)],
        release=[segments.Segment(duration=1, to=0)],
    ).model_dump(mode='json')
    raw['body']['slots'][0]['playback'] = {}
    del raw['body']['slots'][0]['envelope']
    document = SampleInstrumentScore.model_validate(raw)
    restored = parse_score(score_toml(document))
    assert restored == document
    assert restored.body.slots[0].envelope is None
    assert restored.body.slots[0].playback.direction is None
    assert restored.body.slots[0].playback.mode is None
    raw['body']['slots'][0]['envelope'] = envelope.Envelope(
        segments=[segments.Segment(duration=0, to=1)],
        release=[segments.Segment(duration=0, to=0)],
    ).model_dump(mode='json')
    document = SampleInstrumentScore.model_validate(raw)
    assert document.body.slots[0].envelope.release[0].duration == 0
    assert document.body.settings.envelope.release[0].duration == 1


@pytest.mark.parametrize(
    ('section', 'changes', 'message'),
    [
        ('slice', {'asset': 'missing'}, 'Unknown slice asset'),
        ('slice', {'end_frame': 44101}, 'exceeds native asset'),
        ('slice', {'start_frame': 1000}, 'exceed start_frame'),
        ('slice', {'start_frame': True}, 'boolean'),
        ('slice', {'loop': {'start_frame': 0, 'end_frame': 20}}, 'contained'),
        ('slice', {'loop': {'start_frame': 10, 'end_frame': 1001}}, 'contained'),
        ('slot', {'slice': 'missing'}, 'Unknown slice'),
        ('slot', {'sample': 'old.wav'}, 'Extra inputs'),
        ('slot', {'selection': 'missing'}, 'unknown selection'),
        ('slot', {'articulations': ['missing']}, 'unknown articulations'),
        (
            'slot',
            {'chokes': [{'group': 'missing', 'mode': 'release'}]},
            'unknown choke',
        ),
        ('slot', {'trigger': 'release'}, 'one_shot'),
        ('slot', {'channels': []}, 'at least 1'),
        (
            'slot',
            {'channels': [{'input': 'absent', 'output': 'left', 'gain': 1}]},
            'Unknown channel',
        ),
        (
            'slot',
            {'channels': [{'input': 'mono', 'output': 'absent', 'gain': 1}]},
            'Unknown channel',
        ),
        (
            'asset',
            {'location': {'kind': 'relative_file', 'path': '../glass.wav'}},
            'declared root',
        ),
        (
            'asset',
            {'location': {'kind': 'relative_file', 'path': 'audio/../glass.wav'}},
            'declared root',
        ),
        (
            'asset',
            {'location': {'kind': 'relative_file', 'path': '/glass.wav'}},
            'declared root',
        ),
        (
            'asset',
            {
                'location': {
                    'kind': 'relative_file',
                    'path': 'https://example.org/glass.wav',
                }
            },
            'declared root',
        ),
        ('asset', {'content': {'byte_length': 88244, 'sha256': 'unknown'}}, 'pattern'),
    ],
)
def test_instrument_references_are_validated_before_loading(
    section: str, changes: dict[str, object], message: str
) -> None:
    raw = fixture()
    item = (
        raw['assets'][0]
        if section == 'asset'
        else raw['body'][{'slot': 'slots', 'slice': 'slices'}[section]][0]
    )
    item.update(changes)
    with pytest.raises(ValidationError, match=message):
        SampleInstrumentScore.model_validate(raw)


@pytest.mark.parametrize('section', ['assets', 'timebases', 'slices', 'slots'])
def test_native_identifiers_are_unique(section: str) -> None:
    raw = fixture()
    values = (
        raw[section] if section in ('assets', 'timebases') else raw['body'][section]
    )
    values.append(deepcopy(values[0]))
    with pytest.raises(ValidationError, match='duplicate'):
        SampleInstrumentScore.model_validate(raw)


def test_channels_and_ports_are_not_implicit() -> None:
    raw = fixture()
    raw['outputs'].append(raw['outputs'][0])
    with pytest.raises(ValidationError, match='duplicate'):
        SampleInstrumentScore.model_validate(raw)
    raw = fixture()
    raw['assets'][0]['audio']['timebase'] = 'missing'
    with pytest.raises(ValidationError, match='[Uu]nknown.*timebase'):
        SampleInstrumentScore.model_validate(raw)
    raw = fixture()
    raw['outputs'][0]['stream']['timebase'] = 'missing'
    with pytest.raises(ValidationError, match='[Uu]nknown.*timebase'):
        SampleInstrumentScore.model_validate(raw)
    raw = fixture()
    raw['body']['slots'][0]['channels'].append(raw['body']['slots'][0]['channels'][0])
    with pytest.raises(ValidationError, match='duplicate channel route'):
        SampleInstrumentScore.model_validate(raw)


def test_sample_instruments_accept_finite_buffer_providers() -> None:
    raw = fixture()
    asset = raw['assets'][0]
    asset['location'] = {
        'kind': 'python_provider',
        'module': 'show_audio.generators',
        'function': 'glass',
        'delivery': 'buffer',
    }
    del asset['content']
    assert SampleInstrumentScore.model_validate(raw).assets[0].audio.frames == 44100


def test_finite_audio_sources_require_frames() -> None:
    raw = fixture()
    del raw['assets'][0]['audio']['frames']
    with pytest.raises(ValidationError, match='finite audio extent'):
        SampleInstrumentScore.model_validate(raw)


def test_sample_instruments_reject_callback_sources() -> None:
    raw = fixture()
    asset = raw['assets'][0]
    asset['location'] = {
        'kind': 'python_provider',
        'module': 'show_audio.inputs',
        'function': 'stage_feed',
        'delivery': 'callback',
    }
    del asset['content']
    with pytest.raises(ValidationError, match='finite, seekable'):
        SampleInstrumentScore.model_validate(raw)


def test_loop_rules_use_inherited_playback_and_half_open_slice_bounds() -> None:
    raw = fixture()
    raw['body']['slots'][0]['playback'] = {}
    raw['body']['slices'][0]['loop'] = {
        'start_frame': 10,
        'end_frame': 1000,
        'crossfade_frames': 10,
    }
    SampleInstrumentScore.model_validate(raw)
    raw['body']['settings']['playback'] = {'direction': 'mirror'}
    with pytest.raises(ValidationError, match='mirror loops'):
        SampleInstrumentScore.model_validate(raw)
    raw['body']['settings']['playback'] = {'mode': 'one_shot'}
    with pytest.raises(ValidationError, match='while_held'):
        SampleInstrumentScore.model_validate(raw)
    raw['body']['slots'][0]['playback'] = {'direction': 'forward', 'mode': 'while_held'}
    SampleInstrumentScore.model_validate(raw)


def test_whole_sample_repeats_require_one_shot_playback() -> None:
    raw = fixture()
    raw['body']['slots'][0]['playback'] = {'play_count': 2}
    with pytest.raises(ValidationError, match='play_count requires one_shot'):
        SampleInstrumentScore.model_validate(raw)
    raw['body']['slots'][0]['playback']['mode'] = 'one_shot'
    SampleInstrumentScore.model_validate(raw)


@pytest.mark.parametrize(
    ('model', 'raw'),
    [
        (
            playback.Mapping,
            {'lowest_key': 64, 'highest_key': 60, 'reference_pitch_hz': 440},
        ),
        (
            playback.Mapping,
            {'lowest_key': True, 'highest_key': 128, 'pitch_tracking': False},
        ),
        (
            playback.Mapping,
            {'lowest_key': 0, 'highest_key': 128, 'reference_pitch_hz': '440ms'},
        ),
        (playback.Loop, {'start_frame': 0, 'end_frame': 1}),
        (playback.Loop, {'start_frame': 0, 'end_frame': 10, 'crossfade_frames': 1}),
        (playback.Loop, {'start_frame': 0, 'end_frame': 10, 'crossfade_frames': 5}),
        (playback.Loop, {'start_frame': 0, 'end_frame': 10, 'repeat_count': -1}),
        (playback.SlotPlayback, {'play_count': 0}),
        (playback.SlotPlayback, {'start_delay_seconds': -1}),
        (ControlDeclaration, {'default': -0.1}),
        (ControlDeclaration, {'default': float('inf')}),
        (ControlDeclaration, {'polarity': 'bipolar', 'default': -1.01}),
        (
            processing.EqualizerBand,
            {'name': 'tone', 'frequency_hz': 100, 'gain_db': 0, 'resonance': 0},
        ),
        (selection.Choke, {'group': 'hats', 'mode': 'fade'}),
        (selection.Choke, {'group': 'hats', 'mode': 'release', 'fade_seconds': 0.1}),
        (selection.Sustain, {'control': 'sustain', 'threshold': 0}),
        (selection.Articulations, {'ids': ['a', 'a'], 'default': 'a'}),
        (selection.Articulations, {'ids': ['a'], 'default': 'b'}),
        (SampleSettings, {'controls': {'expression': {'default': 1.1}}}),
        (SampleSettings, {'sustain': {'control': 'missing'}}),
        (
            SampleSettings,
            {
                'controls': {'sustain': {'polarity': 'bipolar'}},
                'sustain': {'control': 'sustain'},
            },
        ),
    ],
)
def test_invalid_musical_settings_are_rejected(
    model: type[Model], raw: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(raw)


def test_declarations_are_frozen_with_independent_defaults() -> None:
    first, second = SampleSettings(), SampleSettings()
    with pytest.raises(ValidationError, match='frozen'):
        first.sustain = None
    first.processing.equalizer.append(
        processing.EqualizerBand(name='tone', frequency_hz=100, gain_db=0, resonance=1)
    )
    assert second.processing.equalizer == []
    assert SampleSettings().processing.equalizer == []
    choke = selection.Choke.model_validate({'group': 'hats', 'mode': 'release'})
    assert selection.Choke.model_validate_json(choke.model_dump_json()) == choke


@pytest.mark.parametrize(('field', 'value'), [('pan', 0.2), ('stereo_balance', 0.2)])
@pytest.mark.parametrize('grouped', [False, True])
def test_spatial_controls_reject_inapplicable_channel_layouts(
    field: str, value: float, grouped: bool
) -> None:
    raw = fixture()
    raw['body']['slots'][0]['processing']['pan'] = 0
    raw['body']['slots'][0]['processing'][field] = value
    if grouped:
        raw['body']['groups'] = [
            {'name': 'spatial', 'processing': raw['body']['slots'][0].pop('processing')}
        ]
        raw['body']['slots'][0]['group'] = 'spatial'
    if field == 'pan':
        raw['outputs'][0]['stream']['channels'] = ['mono']
        raw['body']['slots'][0]['channels'] = [
            {'input': 'mono', 'output': 'mono', 'gain': 1}
        ]
    with pytest.raises(ValidationError, match='native layout and stereo output'):
        SampleInstrumentScore.model_validate(raw)


def fixture() -> dict[str, object]:
    return json.loads(Path('conformance/instrument.json').read_text())
