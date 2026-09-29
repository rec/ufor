import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor import envelope, modulation, segments, sfz
from ufor.base import Model
from ufor.codec import migrate_score_v3, parse_score, score_schema, score_toml
from ufor.interface import ScoreReference
from ufor.library import Entry, Library
from ufor.preset import PresetScore
from ufor.samples import crossfade, enums, playback, processing, selection
from ufor.samples.controls import ControlDeclaration
from ufor.samples.instrument import (
    SampleInstrumentScore,
    SampleSettings,
    effective_selection,
    effective_settings,
)
from ufor.samples.metadata import AudioMetadata
from ufor.sfz import registry
from ufor.time import Rate, Timebase


def test_sfz_conformance_requires_only_text_and_supplied_asset_facts() -> None:
    source = sfz.parse(Path('conformance/instrument.sfz').read_text())
    assert sfz.sample_paths(source) == ['audio/glass.wav']
    result = sfz.compile_instrument(
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
    expected = SampleInstrumentScore.model_validate(fixture())
    assert result.instrument.model_dump(
        mode='json', exclude_none=True
    ) == expected.model_dump(mode='json', exclude_none=True)
    assert sfz.write(result.instrument).complete


def test_sfz_reports_missing_sample_metadata() -> None:
    source = sfz.parse('<region> sample=audio/missing.wav')
    with pytest.raises(ValueError, match='audio/missing.wav'):
        sfz.compile_instrument(
            source,
            name='missing',
            title='Missing',
            assets={},
            output_timebase=Timebase(name='output', rate=Rate(numerator=48000)),
            output_channels=['left'],
        )


def test_sfz_key_amplitude_tracking_combines_with_velocity() -> None:
    source = sfz.parse(
        '<region> sample=audio/glass.wav lokey=60 hikey=67 '
        'pitch_keycenter=60 volume=-3 '
        'amp_keycenter=60 amp_keytrack=-1.5 amp_veltrack=100'
    )
    result = sfz.compile_instrument(
        source,
        name='glass',
        title='Glass',
        assets={
            'audio/glass.wav': AudioMetadata(
                channels=1,
                frames=48_000,
                sample_rate=48_000,
                encoding='WAV/PCM_16',
                byte_length=96_044,
                sha256='0' * 64,
                embedded_loop_known=True,
            )
        },
        output_timebase=Timebase(name='output', rate=Rate(numerator=48_000)),
        output_channels=['left', 'right'],
    )

    assert result.complete
    assert result.instrument is not None
    slot = result.instrument.body.slots[0]
    values = modulation.evaluate(
        slot.modulation,
        {
            'key': modulation.SourceValue(value=64),
            'velocity': modulation.SourceValue(value=1),
        },
    )
    assert {v.target.parameter: v.value for v in values} == {
        'amplitude': 1,
        'volume_db': -9,
    }


def test_sfz_partial_pitch_tracking_uses_key_modulation() -> None:
    source = sfz.parse(
        '<region> sample=audio/glass.wav lokey=60 hikey=64 '
        'pitch_keycenter=60 pitch_keytrack=50 tune=10'
    )
    result = sfz.compile_instrument(
        source,
        name='glass',
        title='Glass',
        assets={
            'audio/glass.wav': AudioMetadata(
                channels=1,
                frames=48_000,
                sample_rate=48_000,
                encoding='WAV/PCM_16',
                byte_length=96_044,
                sha256='0' * 64,
                embedded_loop_known=True,
            )
        },
        output_timebase=Timebase(name='output', rate=Rate(numerator=48_000)),
        output_channels=['left', 'right'],
    )

    assert result.complete
    assert result.instrument is not None
    slot = result.instrument.body.slots[0]
    assert slot.mapping.pitch_tracking
    values = modulation.evaluate(
        slot.modulation,
        {
            'key': modulation.SourceValue(value=64),
            'velocity': modulation.SourceValue(value=1),
        },
    )
    tuning = next(v.value for v in values if v.target.parameter == 'tuning_cents')
    assert tuning == -190
    assert playback.pitch_ratio(slot.mapping, 440 * 2 ** ((64 - 69) / 12), tuning) == (
        pytest.approx(2 ** (210 / 1200))
    )


def test_sfz_pitch_velocity_combines_with_key_tracking() -> None:
    source = sfz.parse(
        '<region> sample=audio/glass.wav key=60 hikey=61 '
        'pitch_keytrack=50 pitch_veltrack=1200 amp_veltrack=0 tune=10'
    )
    result = sfz.compile_instrument(
        source,
        name='glass',
        title='Glass',
        assets={
            'audio/glass.wav': AudioMetadata(
                channels=1,
                frames=48_000,
                sample_rate=48_000,
                encoding='WAV/PCM_16',
                byte_length=96_044,
                sha256='0' * 64,
                embedded_loop_known=True,
            )
        },
        output_timebase=Timebase(name='output', rate=Rate(numerator=48_000)),
        output_channels=['left', 'right'],
    )

    assert result.complete
    assert result.instrument is not None
    slot = result.instrument.body.slots[0]
    values = modulation.evaluate(
        slot.modulation,
        {
            'key': modulation.SourceValue(value=61),
            'velocity': modulation.SourceValue(value=64 / 127),
        },
    )
    tuning = next(v.value for v in values if v.target.parameter == 'tuning_cents')
    assert tuning == pytest.approx(10 - 50 + 1200 * 64 / 127)


def test_sfz_velocity_changes_envelope_attack_duration() -> None:
    source = sfz.parse(
        '<region> sample=audio/glass.wav ampeg_attack=0.5 '
        'ampeg_vel2attack=-0.4 amp_veltrack=0'
    )
    result = sfz.compile_instrument(
        source,
        name='glass',
        title='Glass',
        assets={
            'audio/glass.wav': AudioMetadata(
                channels=1,
                frames=48_000,
                sample_rate=48_000,
                encoding='WAV/PCM_16',
                byte_length=96_044,
                sha256='0' * 64,
                embedded_loop_known=True,
            )
        },
        output_timebase=Timebase(name='output', rate=Rate(numerator=48_000)),
        output_channels=['left', 'right'],
    )

    assert result.complete
    assert result.instrument is not None
    slot = result.instrument.body.slots[0]
    assert slot.envelope.segments[1].duration == Fraction(1, 2)
    at_zero = modulation.evaluate(
        slot.modulation, {'velocity': modulation.SourceValue(value=0)}
    )
    at_max = modulation.evaluate(
        slot.modulation, {'velocity': modulation.SourceValue(value=1)}
    )
    assert at_zero[0].value == pytest.approx(0.5)
    assert at_max[0].value == pytest.approx(0.1)


def test_sfz_define_expands_opcode_values_and_preserves_locations() -> None:
    source = sfz.parse(
        '#define $SAMPLE audio/glass.wav\n'
        '#define $KEY 60\n'
        '<region> sample=$SAMPLE key=$KEY\n'
    )

    assert sfz.sample_paths(source) == ['audio/glass.wav']
    assert source.unimplemented == []
    locations = [
        (o.opcode, o.value, o.line, o.column) for o in source.regions[0].opcodes
    ]
    assert locations == [
        ('sample', 'audio/glass.wav', 3, 10),
        ('key', '60', 3, 25),
    ]


def test_sfz_define_uses_the_value_at_each_region() -> None:
    source = sfz.parse(
        '#define $KEY 60\n'
        '<region> sample=a.wav key=$KEY\n'
        '#define $KEY 61\n'
        '<region> sample=b.wav key=$KEY\n'
    )

    assert [r.opcodes[-1].value for r in source.regions] == ['60', '61']


@pytest.mark.parametrize(
    ('definition', 'error'),
    [
        ('', 'Undefined SFZ variable \\$KEY on line 1'),
        ('#define $KEY $KEY\n', 'Recursive SFZ variable \\$KEY on line 2'),
        ('#define $KEY $MISSING\n', 'Undefined SFZ variable \\$MISSING on line 2'),
    ],
)
def test_sfz_define_rejects_undefined_and_recursive_variables(
    definition: str, error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        sfz.parse(f'{definition}<region> sample=a.wav key=$KEY')


@pytest.mark.parametrize(
    ('header', 'reason'),
    [
        ('curve', 'curve-table support'),
        ('effect', 'effect routing support'),
        ('sample', 'sample-definition support'),
    ],
)
def test_sfz_reports_unsupported_header_and_its_opcodes(
    header: str, reason: str
) -> None:
    source = sfz.parse(f'<{header}> unsupported=1\n<region> sample=a.wav')

    assert len(source.unimplemented) == 2
    assert source.unimplemented[0].location.header == header
    assert reason in source.unimplemented[0].reason
    assert source.unimplemented[1].location.opcode == 'unsupported'
    assert source.unimplemented[1].value == '1'


@pytest.mark.parametrize(
    ('opcode', 'classification', 'reason'),
    [
        ('cutoff', registry.Support.new_model, 'filter model'),
        ('locc7', registry.Support.controller_binding, 'controller binding'),
        ('sync_beats', registry.Support.new_model, 'transport and tempo model'),
        ('md5', registry.Support.asset_metadata, 'asset metadata'),
        ('vendor_setting', registry.Support.vendor_extension, 'Vendor'),
    ],
)
def test_sfz_registry_drives_unsupported_diagnostics(
    opcode: str, classification: registry.Support, reason: str
) -> None:
    source = sfz.parse(f'<region> sample=a.wav {opcode}=1')

    assert registry.opcode_support(opcode)[0] == classification
    assert len(source.unimplemented) == 1
    feature = source.unimplemented[0]
    assert feature.location.opcode == opcode
    assert feature.value == '1'
    assert reason in feature.reason


def test_sfz_registry_covers_the_pinned_standard_and_generates_its_table() -> None:
    assert len(registry.STANDARD_OPCODES) == 453
    assert all(
        registry.opcode_support(n)[1] is not None for n in registry.STANDARD_OPCODES
    )
    assert registry.opcode_support('amp_velcurve_64')[0] == registry.Support.supported
    assert registry.opcode_support('ampeg_attack_oncc7')[0] == (
        registry.Support.controller_binding
    )
    assert Path('doc/sfz-support.md').read_text() == registry.support_table()


def test_sfz_random_range_round_trips_without_selection() -> None:
    source = sfz.parse('<region> sample=audio/glass.wav key=60 lorand=0.25 hirand=0.5')
    result = sfz.compile_instrument(
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
    assert result.instrument is not None
    assert result.instrument.body.slots[0].random_range == selection.RandomRange(
        minimum=0.25, maximum=0.5
    )
    rendered = sfz.write(result.instrument)
    assert rendered.complete
    assert 'lorand=0.25' in rendered.contents
    assert 'hirand=0.5' in rendered.contents


def test_sfz_crossfades_do_not_narrow_layer_eligibility() -> None:
    source = sfz.parse(
        '<region> sample=audio/glass.wav lokey=40 hikey=80 '
        'xfin_lokey=50 xfin_hikey=60 xf_keycurve=power '
        'xfin_lovel=32 xfin_hivel=64 xf_velcurve=gain'
    )
    result = sfz.compile_instrument(
        source,
        name='glass',
        title='Glass',
        assets={
            'audio/glass.wav': AudioMetadata(
                channels=1,
                frames=48_000,
                sample_rate=48_000,
                encoding='WAV/PCM_16',
                byte_length=96_044,
                sha256='0' * 64,
                embedded_loop_known=True,
            )
        },
        output_timebase=Timebase(name='output', rate=Rate(numerator=48_000)),
        output_channels=['left', 'right'],
    )
    assert result.complete
    assert result.instrument is not None
    slot = result.instrument.body.slots[0]
    assert (slot.mapping.lowest_key, slot.mapping.highest_key) == (40, 80)
    assert slot.crossfades == [
        crossfade.KeyCrossfade(
            input=enums.CrossfadeInput.key,
            direction=enums.FadeDirection.fade_in,
            start=50,
            end=60,
            curve=enums.FadeCurve.equal_power,
        ),
        crossfade.KeyCrossfade(
            input=enums.CrossfadeInput.velocity,
            direction=enums.FadeDirection.fade_in,
            start=32 / 127,
            end=64 / 127,
        ),
    ]
    rendered = sfz.write(result.instrument)
    assert rendered.complete
    assert 'xfin_lokey=50' in rendered.contents
    assert 'xfin_hivel=64' in rendered.contents


def test_sfz_loop_count_round_trips_as_finite_repeats() -> None:
    source = sfz.parse(
        '<region> sample=audio/glass.wav loop_mode=loop_sustain '
        'loop_start=100 loop_end=999 loop_count=3'
    )
    result = sfz.compile_instrument(
        source,
        name='glass',
        title='Glass',
        assets={
            'audio/glass.wav': AudioMetadata(
                channels=1,
                frames=48_000,
                sample_rate=48_000,
                encoding='WAV/PCM_16',
                byte_length=96_044,
                sha256='0' * 64,
                embedded_loop_known=True,
            )
        },
        output_timebase=Timebase(name='output', rate=Rate(numerator=48_000)),
        output_channels=['left', 'right'],
    )
    assert result.complete
    assert result.instrument is not None
    assert result.instrument.body.slices[0].loop == playback.Loop(
        start_frame=100, end_frame=1000, repeat_count=3
    )
    rendered = sfz.write(result.instrument)
    assert rendered.complete
    assert 'loop_count=3' in rendered.contents


def test_sfz_loop_count_without_loop_is_reported_at_opcode() -> None:
    source = sfz.parse('<region> sample=audio/glass.wav loop_count=2')
    result = sfz.compile_instrument(
        source,
        name='glass',
        title='Glass',
        assets={
            'audio/glass.wav': AudioMetadata(
                channels=1,
                frames=48_000,
                sample_rate=48_000,
                encoding='WAV/PCM_16',
                byte_length=96_044,
                sha256='0' * 64,
                embedded_loop_known=True,
            )
        },
        output_timebase=Timebase(name='output', rate=Rate(numerator=48_000)),
        output_channels=['left', 'right'],
    )
    assert not result.complete
    assert [(i.location.opcode, i.reason) for i in result.unimplemented] == [
        ('loop_count', 'SFZ loop_count requires an active loop')
    ]


def test_sfz_count_overrides_loop_mode_without_retriggering_the_envelope() -> None:
    metadata = AudioMetadata(
        channels=1,
        frames=48_000,
        sample_rate=48_000,
        encoding='WAV/PCM_16',
        byte_length=96_044,
        sha256='0' * 64,
        embedded_loop_known=True,
    )
    source = sfz.parse(
        '<region> sample=audio/glass.wav count=3 loop_mode=loop_continuous '
        'loop_start=100 loop_end=999'
    )
    result = sfz.compile_instrument(
        source,
        name='glass',
        title='Glass',
        assets={'audio/glass.wav': metadata},
        output_timebase=Timebase(name='output', rate=Rate(numerator=48_000)),
        output_channels=['left', 'right'],
    )
    assert result.complete
    assert result.instrument is not None
    slot = result.instrument.body.slots[0]
    assert slot.playback == playback.SlotPlayback(
        mode=enums.PlaybackMode.one_shot, play_count=3
    )
    assert result.instrument.body.slices[0].loop is None
    rendered = sfz.write(result.instrument)
    assert rendered.complete
    assert 'count=3' in rendered.contents

    source = sfz.parse('<region> sample=audio/glass.wav count=0')
    ambiguous = sfz.compile_instrument(
        source,
        name='glass',
        title='Glass',
        assets={'audio/glass.wav': metadata},
        output_timebase=Timebase(name='output', rate=Rate(numerator=48_000)),
        output_channels=['left', 'right'],
    )
    assert [(i.location.opcode, i.reason) for i in ambiguous.unimplemented] == [
        ('count', 'SFZ count=0 differs between players')
    ]


def test_sfz_sequence_requires_explicit_counter_rule() -> None:
    source = sfz.parse(
        '<region> sample=audio/glass.wav key=60 seq_length=2 seq_position=1'
    )
    metadata = AudioMetadata(
        channels=1,
        frames=48_000,
        sample_rate=48_000,
        encoding='WAV/PCM_16',
        byte_length=96_044,
        sha256='0' * 64,
        embedded_loop_known=True,
    )
    kwargs = dict(
        name='glass',
        title='Glass',
        assets={'audio/glass.wav': metadata},
        output_timebase=Timebase(name='output', rate=Rate(numerator=48_000)),
        output_channels=['left', 'right'],
    )

    default = sfz.compile_instrument(source, **kwargs)
    opted_in = sfz.compile_instrument(source, sequence_counter='all_note_ons', **kwargs)

    assert [i.location.opcode for i in default.unimplemented] == [
        'seq_length',
        'seq_position',
    ]
    assert opted_in.complete
    assert opted_in.instrument is not None
    assert opted_in.instrument.body.slots[0].sequence == selection.SequencePosition(
        length=2, position=1
    )
    exported = sfz.write(opted_in.instrument)
    assert not exported.complete
    assert exported.unimplemented[0].location.path == 'body.slots[0].sequence'
    assert 'seq_length=2' in exported.contents
    assert 'seq_position=1' in exported.contents


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
            {'lowest_key': 0, 'highest_key': 128, 'reference_pitch_hz': '440Hz'},
        ),
        (playback.Loop, {'start_frame': 0, 'end_frame': 1}),
        (playback.Loop, {'start_frame': 0, 'end_frame': 10, 'crossfade_frames': 1}),
        (playback.Loop, {'start_frame': 0, 'end_frame': 10, 'crossfade_frames': 5}),
        (playback.Loop, {'start_frame': 0, 'end_frame': 10, 'repeat_count': -1}),
        (playback.SlotPlayback, {'play_count': 0}),
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


def test_sfz_reports_general_envelopes_and_custom_channel_maps_as_unsupported() -> None:
    raw = fixture()
    raw['body']['slots'][0]['envelope']['segments'][1]['curve'] = 2
    raw['body']['slots'][0]['channels'][0]['gain'] = 0.125
    raw['body']['slots'][0]['processing']['pan'] = 0
    result = sfz.write(SampleInstrumentScore.model_validate(raw))
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
    result = sfz.write(SampleInstrumentScore.model_validate(raw))
    assert not result.complete
    assert result.unimplemented[0].location.path == 'body.slots[0].modulation.routes[0]'
    assert 'amp_velcurve_127=2' not in result.contents


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


def test_sfz_generator_diagnostics_use_dictionary_paths() -> None:
    raw = fixture()
    raw['body']['slots'][0]['motions'] = {
        'vibrato': {'body': {'kind': 'cycle', 'rate': 5}}
    }
    result = sfz.write(SampleInstrumentScore.model_validate(raw))
    assert not result.complete
    assert result.unimplemented[0].location.path == 'body.slots[0].motions.vibrato'


def test_sfz_export_resolves_group_processing() -> None:
    raw = fixture()
    settings = raw['body']['slots'][0].pop('processing')
    settings['volume_db'] = -6
    raw['body']['groups'] = [{'name': 'quiet', 'processing': settings}]
    raw['body']['slots'][0]['group'] = 'quiet'
    result = sfz.write(SampleInstrumentScore.model_validate(raw))
    assert result.complete
    assert 'volume=-6' in result.contents


@pytest.mark.parametrize(
    'field,value,path',
    [
        ('variation', {'pitch_cents': 5}, 'body.slots[0].variation.pitch_cents'),
        (
            'filters',
            [{'name': 'tone', 'response': 'lowpass', 'cutoff_hz': 1000}],
            'body.slots[0].processing.filters[0]',
        ),
        ('voice_policy', {'maximum_voices': 4}, 'body.settings.voice_policy'),
    ],
)
def test_sfz_reports_unrepresentable_native_features(
    field: str, value: object, path: str
) -> None:
    raw = fixture()
    if field == 'voice_policy':
        raw['body']['settings'][field] = value
    elif field == 'filters':
        raw['body']['slots'][0]['processing'][field] = value
    else:
        raw['body']['slots'][0][field] = value
    result = sfz.write(SampleInstrumentScore.model_validate(raw))
    assert not result.complete
    assert path in [i.location.path for i in result.unimplemented]


@pytest.mark.parametrize('sample', ['../outside.wav', '/outside.wav', 'C:/outside.wav'])
def test_sfz_paths_are_validated_before_requesting_asset_facts(sample: str) -> None:
    source = sfz.parse(f'<region> sample={sample}')
    with pytest.raises(ValueError, match='declared root'):
        sfz.sample_paths(source)


def fixture() -> dict[str, object]:
    return json.loads(Path('conformance/instrument.json').read_text())
