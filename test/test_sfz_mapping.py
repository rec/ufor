from typing import Literal

import pytest

from ufor import sfz
from ufor.events import ControlChange, Release, Trigger
from ufor.interface import ScoreReference
from ufor.samples import trace
from ufor.samples.enums import ChokeMode, VoiceOverflow
from ufor.samples.instrument import SampleInstrumentScore
from ufor.samples.metadata import AudioMetadata
from ufor.samples.processing import ChannelRoute
from ufor.sfz.model import SfzMidiBindingRequest
from ufor.time import Rate, Timebase


def test_sfz_sticky_keyswitches_select_regions_and_clear_on_unmapped_key() -> None:
    result = _compile(
        '<global> sw_lokey=24 sw_hikey=26 sw_default=24 '
        '<region> sample=sample.wav key=60 sw_last=24 '
        '<region> sample=sample.wav key=60 sw_last=26'
    )

    assert result.complete
    assert result.instrument is not None
    events = [
        Trigger(tick=0, ordinal=0, part='main', trigger_id='first', key=60),
        Trigger(tick=1, ordinal=1, part='main', trigger_id='switch', key=26),
        Release(tick=2, ordinal=2, part='main', trigger_id='switch'),
        Trigger(tick=3, ordinal=3, part='main', trigger_id='second', key=60),
        Trigger(tick=4, ordinal=4, part='main', trigger_id='clear', key=25),
        Trigger(tick=5, ordinal=5, part='main', trigger_id='third', key=60),
    ]
    prepared = trace.prepare(result.instrument.body, events, seed=1)

    starts = [a for a in prepared.actions if isinstance(a, trace.VoiceStart)]
    assert [(a.tick, a.template) for a in starts] == [
        (0, 'region-1'),
        (3, 'region-2'),
    ]
    assert prepared.snapshots[-1].selection.articulations == {'main': None}


def test_sfz_controller_condition_uses_part_cc_and_midi_binding() -> None:
    result = _compile(
        '<region> sample=sample.wav key=60 locc74=64 hicc74=127',
        midi_binding=SfzMidiBindingRequest(
            instrument=ScoreReference(path='instrument.toml'),
            part='main',
            repeated_key_release='newest',
        ),
    )

    assert result.complete
    assert result.instrument is not None
    assert result.binding is not None
    assert [(c.number, c.control) for c in result.binding.body.midi[0].controllers] == [
        (64, 'sustain'),
        (74, 'cc-74'),
    ]
    prepared = trace.prepare(
        result.instrument.body,
        [
            Trigger(tick=0, ordinal=0, part='main', trigger_id='before', key=60),
            ControlChange(
                tick=1,
                ordinal=1,
                part='main',
                scope='part',
                control='cc-74',
                value=64 / 127,
            ),
            Trigger(tick=2, ordinal=2, part='main', trigger_id='after', key=60),
        ],
        seed=1,
    )

    starts = [a for a in prepared.actions if isinstance(a, trace.VoiceStart)]
    assert [(a.tick, a.template) for a in starts] == [(2, 'region-1')]


def test_sfz_keyswitch_without_range_remains_diagnosed() -> None:
    result = _compile('<region> sample=sample.wav sw_last=24')

    assert result.instrument is not None
    assert not result.complete
    assert [i.location.opcode for i in result.unimplemented] == ['sw_last']


def test_sfz_controller_condition_without_binding_remains_diagnosed() -> None:
    result = _compile('<region> sample=sample.wav locc74=64')

    assert result.instrument is not None
    assert not result.complete
    assert result.instrument.body.slots[0].control_conditions[0].control == 'cc-74'
    assert [i.location.opcode for i in result.unimplemented] == ['locc74']


def test_pitch_alias_and_tune_follow_inheritance_order() -> None:
    result = _compile(
        '<global> pitch=11 <region> sample=sample.wav tune=3 '
        '<region> sample=sample.wav pitch=7'
    )

    assert result.complete
    assert result.instrument is not None
    assert [s.processing.tuning_cents for s in result.instrument.body.slots] == [3, 7]
    assert sfz.write(result.instrument).complete


def test_conflicting_pitch_center_before_key_is_diagnosed() -> None:
    result = _compile('<global> pitch_keycenter=60 <region> sample=sample.wav key=72')

    assert not result.complete
    assert len(result.unimplemented) == 1
    assert result.unimplemented[0].location.opcode == 'key'
    assert 'players disagree' in result.unimplemented[0].reason


def test_key_before_pitch_center_is_unambiguous() -> None:
    result = _compile('<region> sample=sample.wav key=72 pitch_keycenter=60')

    assert result.complete
    assert result.instrument is not None
    assert result.instrument.body.slots[0].mapping.lowest_key == 72
    assert result.instrument.body.slots[0].mapping.reference_pitch_hz == pytest.approx(
        261.625565
    )


def test_release_sequence_requires_a_distinct_counter_rule() -> None:
    result = _compile(
        '<region> sample=sample.wav trigger=release seq_length=2 seq_position=1',
        sequence_counter='all_note_ons',
    )

    assert not result.complete
    assert result.instrument is not None
    assert result.instrument.body.slots[0].sequence is None
    assert [i.location.opcode for i in result.unimplemented] == [
        'seq_length',
        'seq_position',
    ]
    assert all('note-on triggers' in i.reason for i in result.unimplemented)


def test_release_random_range_requires_the_original_note_on_draw() -> None:
    result = _compile(
        '<region> sample=sample.wav trigger=release lorand=0.25 hirand=0.5'
    )

    assert not result.complete
    assert result.instrument is not None
    assert result.instrument.body.slots[0].random_range is None
    assert [i.location.opcode for i in result.unimplemented] == [
        'lorand',
        'hirand',
    ]
    assert all('note-on draw' in i.reason for i in result.unimplemented)


def test_release_controller_condition_requires_the_note_on_value() -> None:
    result = _compile(
        '<region> sample=sample.wav trigger=release locc7=64',
        midi_binding=SfzMidiBindingRequest(
            instrument=ScoreReference(path='instrument.toml'),
            part='part',
            repeated_key_release='newest',
        ),
    )

    assert not result.complete
    assert result.instrument is not None
    assert not result.instrument.body.slots[0].control_conditions
    assert [i.location.opcode for i in result.unimplemented] == ['locc7']
    assert 'note-on value' in result.unimplemented[0].reason


def test_sfz_sample_end_fade_round_trips() -> None:
    result = _compile(
        '<region> sample=sample.wav loop_mode=no_loop sample_fadeout=0.25'
    )

    assert result.complete
    assert result.instrument is not None
    assert result.instrument.body.slots[0].playback.end_fade_seconds == 0.25
    exported = sfz.write(result.instrument)
    assert exported.complete
    assert 'sample_fadeout=0.25' in exported.contents
    restored = _compile(exported.contents)
    assert restored.instrument is not None
    assert restored.instrument.body.slots[0].playback.end_fade_seconds == 0.25


def test_sfz_full_stereo_width_swap_round_trips() -> None:
    result = _compile(
        '<region> sample=sample.wav width=-100',
        output_channels=['left', 'right'],
        sample_channels=2,
    )

    assert result.complete
    assert result.instrument is not None
    assert result.instrument.body.slots[0].channels == [
        ChannelRoute(input='left', output='right', gain=1),
        ChannelRoute(input='right', output='left', gain=1),
    ]
    exported = sfz.write(result.instrument)
    assert exported.complete
    assert 'width=-100' in exported.contents
    restored = _compile(
        exported.contents, output_channels=['left', 'right'], sample_channels=2
    )
    assert restored.instrument is not None
    assert (
        restored.instrument.body.slots[0].channels
        == result.instrument.body.slots[0].channels
    )


def test_sfz_envelope_start_level_persists_through_delay() -> None:
    result = _compile(
        '<region> sample=sample.wav ampeg_start=25 ampeg_delay=0.1 ampeg_attack=0.2'
    )

    assert result.complete
    assert result.instrument is not None
    envelope = result.instrument.body.slots[0].envelope
    assert envelope is not None
    assert envelope.initial == 0.25
    assert envelope.segments[0].to == 0.25
    exported = sfz.write(result.instrument)
    assert exported.complete
    assert 'ampeg_start=25' in exported.contents
    restored = _compile(exported.contents)
    assert restored.instrument is not None
    assert restored.instrument.body.slots[0].envelope == envelope


@pytest.mark.parametrize('start', ['-1', '101', 'nan'])
def test_sfz_envelope_start_rejects_out_of_range_level(start: str) -> None:
    with pytest.raises(ValueError, match='ampeg_start'):
        _compile(f'<region> sample=sample.wav ampeg_start={start}')


@pytest.mark.parametrize('settings', ['width=50', 'width=-100 pan=25'])
def test_sfz_width_without_exact_channel_mapping_is_diagnosed(settings: str) -> None:
    result = _compile(
        f'<region> sample=sample.wav {settings}',
        output_channels=['left', 'right'],
        sample_channels=2,
    )

    assert not result.complete
    assert result.instrument is not None
    assert result.unimplemented[0].location.opcode == 'width'


@pytest.mark.parametrize(
    'settings',
    [
        'loop_mode=loop_sustain loop_start=10 loop_end=99',
        'count=2',
    ],
)
def test_sfz_end_fade_with_repetition_is_diagnosed(settings: str) -> None:
    result = _compile(f'<region> sample=sample.wav {settings} sample_fadeout=0.25')

    assert not result.complete
    assert result.instrument is not None
    assert result.instrument.body.slots[0].playback.end_fade_seconds == 0
    assert result.unimplemented[0].location.opcode == 'sample_fadeout'


@pytest.mark.parametrize('fade', ['-0.1', 'inf', 'nan'])
def test_sfz_end_fade_requires_finite_nonnegative_seconds(fade: str) -> None:
    with pytest.raises(ValueError, match='sample_fadeout'):
        _compile(f'<region> sample=sample.wav sample_fadeout={fade}')


@pytest.mark.parametrize('transpose', ['1.5', '128', '-128'])
def test_transpose_requires_an_in_range_integer(transpose: str) -> None:
    with pytest.raises(ValueError, match='transpose'):
        _compile(f'<region> sample=sample.wav transpose={transpose}')


@pytest.mark.parametrize('tune', ['100.5', '101', '-101'])
def test_tune_requires_an_in_range_integer(tune: str) -> None:
    with pytest.raises(ValueError, match='tune'):
        _compile(f'<region> sample=sample.wav tune={tune}')


@pytest.mark.parametrize('volume', ['6.1', '-144.1'])
def test_volume_must_fit_the_standard_sfz_range(volume: str) -> None:
    with pytest.raises(ValueError, match='volume'):
        _compile(f'<region> sample=sample.wav volume={volume}')


@pytest.mark.parametrize('tuning', [-12800, 12800])
def test_tuning_at_the_sfz_limit_round_trips(tuning: int) -> None:
    transpose = 127 if tuning > 0 else -127
    tune = tuning - 100 * transpose
    result = _compile(f'<region> sample=sample.wav transpose={transpose} tune={tune}')

    assert result.complete
    assert result.instrument is not None
    exported = sfz.write(result.instrument)
    assert exported.complete
    assert f'tune={100 if tuning > 0 else -100}' in exported.contents
    restored = _compile(exported.contents)
    assert restored.instrument is not None
    assert restored.instrument.body.slots[0].processing.tuning_cents == tuning


@pytest.mark.parametrize(
    ('field', 'value', 'reason'),
    [
        ('tuning_cents', 0.5, 'integral-cent'),
        ('tuning_cents', 12801, 'exceeds SFZ'),
        ('volume_db', 6.1, 'exceeds the SFZ range'),
    ],
)
def test_nonrepresentable_processing_is_diagnosed(
    field: str, value: float, reason: str
) -> None:
    compiled = _compile('<region> sample=sample.wav')
    assert compiled.instrument is not None
    raw = compiled.instrument.model_dump()
    raw['body']['slots'][0]['processing'][field] = value
    instrument = SampleInstrumentScore.model_validate(raw)

    exported = sfz.write(instrument)

    assert not exported.complete
    assert any(reason in issue.reason for issue in exported.unimplemented)


def test_sfz_off_by_marks_the_victim_not_the_trigger() -> None:
    source = (
        '<region> sample=sample.wav key=42 group=1 off_by=2 off_mode=normal '
        '<region> sample=sample.wav key=46 group=2'
    )
    result = _compile(source)

    assert result.complete
    assert result.instrument is not None
    victim, trigger = result.instrument.body.slots
    assert victim.choke_group is not None
    assert victim.chokes == []
    assert trigger.choke_group is None
    assert len(trigger.chokes) == 1
    assert trigger.chokes[0].group == victim.choke_group
    assert trigger.chokes[0].mode == ChokeMode.release

    exported = sfz.write(result.instrument)
    assert exported.complete
    restored = _compile(exported.contents)
    assert restored.complete
    assert restored.instrument is not None
    victim, trigger = restored.instrument.body.slots
    assert trigger.chokes[0].group == victim.choke_group
    assert trigger.chokes[0].mode == ChokeMode.release


def test_sfz_off_by_keeps_each_victims_off_mode() -> None:
    source = (
        '<region> sample=sample.wav key=42 group=1 '
        '<region> sample=sample.wav key=44 off_by=1 off_mode=fast '
        '<region> sample=sample.wav key=46 off_by=1 off_mode=normal'
    )
    result = _compile(source)

    assert result.complete
    assert result.instrument is not None
    trigger, fast, normal = result.instrument.body.slots
    assert {c.group: c.mode for c in trigger.chokes} == {
        fast.choke_group: ChokeMode.immediate,
        normal.choke_group: ChokeMode.release,
    }

    exported = sfz.write(result.instrument)
    assert exported.complete
    restored = _compile(exported.contents)
    assert restored.complete
    assert restored.instrument is not None
    trigger, fast, normal = restored.instrument.body.slots
    assert {c.group: c.mode for c in trigger.chokes} == {
        fast.choke_group: ChokeMode.immediate,
        normal.choke_group: ChokeMode.release,
    }


def test_sfz_group_identity_uses_numeric_value() -> None:
    result = _compile(
        '<region> sample=sample.wav group=01 '
        '<region> sample=sample.wav off_by=1 '
        '<region> sample=sample.wav group=00 off_by=+0'
    )

    assert result.complete
    assert result.instrument is not None
    trigger, victim, ungrouped = result.instrument.body.slots
    assert victim.choke_group == trigger.chokes[0].group
    assert ungrouped.choke_group is None
    assert ungrouped.chokes == []


@pytest.mark.parametrize('group', [str(2**31), str(-(2**31) - 1)])
def test_sfz_group_must_fit_the_standard_range(group: str) -> None:
    with pytest.raises(ValueError, match='signed 32-bit'):
        _compile(f'<region> sample=sample.wav group={group}')


def test_sfz_phase_inversion_round_trips_as_native_processing() -> None:
    result = _compile(
        '<region> sample=sample.wav phase=invert pan=25',
        output_channels=['left', 'right'],
    )

    assert result.complete
    assert result.instrument is not None
    assert result.instrument.body.slots[0].processing.invert_polarity
    assert result.instrument.body.slots[0].processing.pan == 0.25
    exported = sfz.write(result.instrument)
    assert exported.complete
    assert 'phase=invert' in exported.contents
    restored = _compile(exported.contents, output_channels=['left', 'right'])
    assert restored.instrument is not None
    assert restored.instrument.body.slots[0].processing.invert_polarity
    assert restored.instrument.body.slots[0].processing.pan == 0.25


def test_sfz_phase_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match='Unsupported SFZ phase'):
        _compile('<region> sample=sample.wav phase=reverse')


def test_silent_region_reports_unsupported_choke_behavior() -> None:
    result = _compile('<region> sample=sample.wav end=-1 group=1 off_by=1')

    assert result.instrument is None
    assert not result.complete
    assert len(result.unimplemented) == 1
    assert result.unimplemented[0].location.opcode == 'end'
    assert 'choke other voices' in result.unimplemented[0].reason


def test_sfz_polyphony_maps_group_with_diagnosed_default() -> None:
    text = (
        '<group> group=7 polyphony=2 '
        '<region> sample=sample.wav key=60 '
        '<region> sample=sample.wav key=61'
    )
    default = _compile(text)
    accepted = _compile(text, polyphony_overflow='oldest_immediate')

    assert default.instrument is not None
    assert not default.complete
    assert [i.location.opcode for i in default.unimplemented] == ['polyphony']
    assert 'oldest-immediate' in default.unimplemented[0].reason
    assert accepted.complete
    assert accepted.instrument is not None
    assert accepted.instrument.body.voice_pools[0].name == 'sfz-group-7'
    assert accepted.instrument.body.voice_pools[0].policy.maximum_voices == 2
    assert (
        accepted.instrument.body.voice_pools[0].policy.overflow
        == VoiceOverflow.replace_oldest
    )
    assert {s.voice_pool for s in accepted.instrument.body.slots} == {'sfz-group-7'}


def test_sfz_polyphony_keeps_conflicting_limits_and_legato_visible() -> None:
    conflict = _compile(
        '<region> sample=sample.wav group=2 polyphony=2 key=60 '
        '<region> sample=sample.wav group=2 polyphony=3 key=61',
        polyphony_overflow='oldest_immediate',
    )
    legato = _compile(
        '<region> sample=sample.wav polyphony=legato_high',
        polyphony_overflow='oldest_immediate',
    )

    assert conflict.instrument is not None
    assert conflict.instrument.body.voice_pools == []
    assert [i.location.opcode for i in conflict.unimplemented] == [
        'polyphony',
        'polyphony',
    ]
    assert legato.instrument is not None
    assert legato.instrument.body.voice_pools == []
    assert [i.location.opcode for i in legato.unimplemented] == ['polyphony']


def test_sfz_polyphony_reports_simultaneous_layers_above_limit() -> None:
    result = _compile(
        '<group> polyphony=1 '
        '<region> sample=sample.wav key=60 '
        '<region> sample=sample.wav key=60',
        polyphony_overflow='oldest_immediate',
    )

    assert result.instrument is not None
    assert len(result.instrument.body.voice_pools) == 1
    assert [i.location.opcode for i in result.unimplemented] == ['polyphony']
    assert 'simultaneous region layers' in result.unimplemented[0].reason


def test_sfz_polyphony_distinguishes_unnumbered_group_headers() -> None:
    result = _compile(
        '<group> polyphony=1 <region> sample=sample.wav key=60\n'
        '<group> polyphony=2 <region> sample=sample.wav key=61',
        polyphony_overflow='oldest_immediate',
    )

    assert result.complete
    assert result.instrument is not None
    assert len(result.instrument.body.voice_pools) == 2
    assert (
        result.instrument.body.slots[0].voice_pool
        != result.instrument.body.slots[1].voice_pool
    )


def _compile(
    text: str,
    output_channels: list[str] | None = None,
    sequence_counter: Literal['reject', 'all_note_ons'] = 'reject',
    polyphony_overflow: Literal['diagnose', 'oldest_immediate'] = 'diagnose',
    sample_channels: int = 1,
    midi_binding: SfzMidiBindingRequest | None = None,
) -> sfz.SfzCompileResult:
    return sfz.compile_instrument(
        sfz.parse(text),
        name='mapping',
        title='Mapping',
        assets={
            'sample.wav': AudioMetadata(
                channels=sample_channels,
                frames=48000,
                sample_rate=48000,
                encoding='WAV/PCM_16',
                byte_length=96044,
                sha256='0' * 64,
                embedded_loop_known=True,
            )
        },
        output_timebase=Timebase(name='output', rate=Rate(numerator=48000)),
        output_channels=output_channels or ['mono'],
        sequence_counter=sequence_counter,
        polyphony_overflow=polyphony_overflow,
        midi_binding=midi_binding,
    )
