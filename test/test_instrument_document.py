import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor import envelope, sfz
from ufor.base import Model
from ufor.codec import parse_score, score_schema, score_toml
from ufor.samples import playback, processing, selection
from ufor.samples.controls import Control
from ufor.samples.instrument import Instrument, InstrumentScore
from ufor.samples.metadata import AudioMetadata
from ufor.time import Rate, Timebase


def test_sfz_conformance_requires_only_text_and_supplied_asset_facts() -> None:
    source = sfz.parse(Path('conformance/instrument.sfz').read_text())
    assert sfz.sample_paths(source) == ['audio/glass.wav']
    result = sfz.compile(
        source,
        name='glass',
        title='Glass',
        assets={
            'audio/glass.wav': AudioMetadata(
                channels=1,
                frames=44100,
                sample_rate=44100,
                encoding='WAV/PCM_16',
                byte_length=88244,
                sha256='0' * 64,
                embedded_loop_known=True,
            )
        },
        output_timebase=Timebase(name='output', rate=Rate(numerator=48000)),
        output_channels=['left', 'right'],
    )
    assert result.complete
    assert result.instrument.model_dump(mode='json') == fixture()
    assert sfz.write(result.instrument).complete


def test_native_instrument_round_trips_through_the_common_codec() -> None:
    document = InstrumentScore.model_validate(fixture())
    assert parse_score(score_toml(document)) == document
    assert InstrumentScore.model_validate_json(document.model_dump_json()) == document
    assert json.loads(Path('schema/scores.json').read_text()) == score_schema()
    assert document.body.slots[0].envelope.segments[1].duration == Fraction(1, 100)
    assert document.assets[0].audio.timebase == 'native-44100'
    assert document.outputs[0].stream.timebase == 'output'
    assert document.body.slices[0].end_frame == 1000


def test_documented_native_example_is_complete() -> None:
    text = (
        Path('doc/instrument-format.md')
        .read_text()
        .split('```toml\n', 1)[1]
        .split('```', 1)[0]
    )
    document = parse_score(text)
    assert isinstance(document, InstrumentScore)
    assert parse_score(score_toml(document)) == document


@pytest.mark.parametrize('version', [True, 2.0, '2', 1])
def test_instrument_version_requires_integer_one(version: object) -> None:
    with pytest.raises(ValidationError):
        InstrumentScore.model_validate(fixture() | {'version': version})


def test_whole_envelope_overrides_and_playback_inheritance_round_trip() -> None:
    raw = fixture()
    raw['body']['instrument']['playback'] = {
        'direction': 'backward',
        'mode': 'one_shot',
    }
    raw['body']['instrument']['envelope'] = envelope.Envelope(
        segments=[envelope.Segment(duration=1, target=1)],
        release=[envelope.Segment(duration=1, target=0)],
    ).model_dump(mode='json')
    raw['body']['slots'][0]['playback'] = {}
    del raw['body']['slots'][0]['envelope']
    document = InstrumentScore.model_validate(raw)
    restored = parse_score(score_toml(document))
    assert restored == document
    assert restored.body.slots[0].envelope is None
    assert restored.body.slots[0].playback.direction is None
    assert restored.body.slots[0].playback.mode is None
    raw['body']['slots'][0]['envelope'] = envelope.Envelope(
        segments=[envelope.Segment(duration=0, target=1)],
        release=[envelope.Segment(duration=0, target=0)],
    ).model_dump(mode='json')
    document = InstrumentScore.model_validate(raw)
    assert document.body.slots[0].envelope.release[0].duration == 0
    assert document.body.instrument.envelope.release[0].duration == 1


@pytest.mark.parametrize(
    ('section', 'changes', 'message'),
    [
        ('slice', {'asset': 'missing'}, 'Unknown slice asset'),
        ('slice', {'end_frame': 44101}, 'exceeds native asset'),
        ('slice', {'start_frame': 1000}, 'exceed start_frame'),
        ('slice', {'start_frame': True}, 'integer'),
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
        ('asset', {'path': '../glass.wav'}, 'document directory'),
        ('asset', {'path': 'audio/../glass.wav'}, 'document directory'),
        ('asset', {'path': '/glass.wav'}, 'document directory'),
        ('asset', {'path': 'https://example.org/glass.wav'}, 'document directory'),
        ('asset', {'sha256': 'unknown'}, 'pattern'),
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
        InstrumentScore.model_validate(raw)


@pytest.mark.parametrize('section', ['assets', 'timebases', 'slices', 'slots'])
def test_native_identifiers_are_unique(section: str) -> None:
    raw = fixture()
    values = (
        raw[section] if section in ('assets', 'timebases') else raw['body'][section]
    )
    values.append(deepcopy(values[0]))
    with pytest.raises(ValidationError, match='duplicate'):
        InstrumentScore.model_validate(raw)


def test_channels_and_ports_are_not_implicit() -> None:
    raw = fixture()
    raw['outputs'].append(raw['outputs'][0])
    with pytest.raises(ValidationError, match='duplicate'):
        InstrumentScore.model_validate(raw)
    raw = fixture()
    raw['assets'][0]['audio']['timebase'] = 'missing'
    with pytest.raises(ValidationError, match='[Uu]nknown.*timebase'):
        InstrumentScore.model_validate(raw)
    raw = fixture()
    raw['outputs'][0]['stream']['timebase'] = 'missing'
    with pytest.raises(ValidationError, match='[Uu]nknown.*timebase'):
        InstrumentScore.model_validate(raw)
    raw = fixture()
    raw['body']['slots'][0]['channels'].append(raw['body']['slots'][0]['channels'][0])
    with pytest.raises(ValidationError, match='duplicate channel route'):
        InstrumentScore.model_validate(raw)


def test_loop_rules_use_inherited_playback_and_half_open_slice_bounds() -> None:
    raw = fixture()
    raw['body']['slots'][0]['playback'] = {}
    raw['body']['slices'][0]['loop'] = {
        'start_frame': 10,
        'end_frame': 1000,
        'crossfade_frames': 10,
    }
    InstrumentScore.model_validate(raw)
    raw['body']['instrument']['playback'] = {'direction': 'mirror'}
    with pytest.raises(ValidationError, match='mirror loops'):
        InstrumentScore.model_validate(raw)
    raw['body']['instrument']['playback'] = {'mode': 'one_shot'}
    with pytest.raises(ValidationError, match='while_held'):
        InstrumentScore.model_validate(raw)
    raw['body']['slots'][0]['playback'] = {'direction': 'forward', 'mode': 'while_held'}
    InstrumentScore.model_validate(raw)


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
            {'lowest_key': 0, 'highest_key': 128, 'reference_pitch_hz': '440Hz'},
        ),
        (playback.Loop, {'start_frame': 0, 'end_frame': 1}),
        (playback.Loop, {'start_frame': 0, 'end_frame': 10, 'crossfade_frames': 1}),
        (playback.Loop, {'start_frame': 0, 'end_frame': 10, 'crossfade_frames': 5}),
        (Control, {'default': -0.1}),
        (Control, {'default': float('inf')}),
        (Control, {'polarity': 'bipolar', 'default': -1.01}),
        (
            processing.EqualizerBand,
            {'name': 'tone', 'frequency_hz': 100, 'gain_db': 0, 'resonance': 0},
        ),
        (selection.Choke, {'group': 'hats', 'mode': 'fade'}),
        (selection.Choke, {'group': 'hats', 'mode': 'release', 'fade_seconds': 0.1}),
        (selection.Sustain, {'control': 'sustain', 'threshold': 0}),
        (selection.Articulations, {'ids': ['a', 'a'], 'default': 'a'}),
        (selection.Articulations, {'ids': ['a'], 'default': 'b'}),
        (Instrument, {'controls': {'expression': {'default': 1.1}}}),
        (Instrument, {'sustain': {'control': 'missing'}}),
        (
            Instrument,
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
    first, second = Instrument(), Instrument()
    with pytest.raises(ValidationError, match='frozen'):
        first.sustain = None
    first.processing.equalizer.append(
        processing.EqualizerBand(name='tone', frequency_hz=100, gain_db=0, resonance=1)
    )
    assert second.processing.equalizer == []
    assert Instrument().processing.equalizer == []
    choke = selection.Choke.model_validate({'group': 'hats', 'mode': 'release'})
    assert selection.Choke.model_validate_json(choke.model_dump_json()) == choke


def test_sfz_reports_general_envelopes_and_custom_channel_maps_as_unsupported() -> None:
    raw = fixture()
    raw['body']['slots'][0]['envelope']['segments'][1]['curve'] = 2
    raw['body']['slots'][0]['channels'][0]['gain'] = 0.125
    raw['body']['slots'][0]['processing']['pan'] = 0
    result = sfz.write(InstrumentScore.model_validate(raw))
    assert not result.complete
    assert [x.location.path for x in result.unimplemented] == [
        'body.slots[0].channels',
        'body.slots[0].envelope',
    ]


def test_sfz_rejects_velocity_gain_outside_its_representable_domain() -> None:
    raw = fixture()
    settings = raw['body']['slots'][0]
    settings['modulation']['parameters'][0]['maximum'] = 2
    settings['modulation']['routes'][0]['points'][-1]['amount'] = 2
    result = sfz.write(InstrumentScore.model_validate(raw))
    assert not result.complete
    assert result.unimplemented[0].location.path == 'body.slots[0].modulation.routes[0]'
    assert 'amp_velcurve_127=2' not in result.contents


@pytest.mark.parametrize(('field', 'value'), [('pan', 0.2), ('stereo_balance', 0.2)])
def test_spatial_controls_reject_inapplicable_channel_layouts(
    field: str, value: float
) -> None:
    raw = fixture()
    raw['body']['slots'][0]['processing']['pan'] = 0
    raw['body']['slots'][0]['processing'][field] = value
    if field == 'pan':
        raw['outputs'][0]['stream']['channels'] = ['mono']
        raw['body']['slots'][0]['channels'] = [
            {'input': 'mono', 'output': 'mono', 'gain': 1}
        ]
    with pytest.raises(ValidationError, match='native layout and stereo output'):
        InstrumentScore.model_validate(raw)


def test_sfz_generator_diagnostics_use_dictionary_paths() -> None:
    raw = fixture()
    raw['body']['slots'][0]['lfos'] = {'vibrato': {'rate': 5}}
    result = sfz.write(InstrumentScore.model_validate(raw))
    assert not result.complete
    assert result.unimplemented[0].location.path == 'body.slots[0].lfos.vibrato'


@pytest.mark.parametrize('sample', ['../outside.wav', '/outside.wav', 'C:/outside.wav'])
def test_sfz_paths_are_validated_before_requesting_asset_facts(sample: str) -> None:
    source = sfz.parse(f'<region> sample={sample}')
    with pytest.raises(ValueError, match='document directory'):
        sfz.sample_paths(source)


def fixture() -> dict[str, object]:
    return json.loads(Path('conformance/instrument.json').read_text())
