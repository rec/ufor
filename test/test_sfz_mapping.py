import pytest

from ufor import sfz
from ufor.samples.enums import ChokeMode
from ufor.samples.instrument import SampleInstrumentScore
from ufor.samples.metadata import AudioMetadata
from ufor.time import Rate, Timebase


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


def _compile(
    text: str, output_channels: list[str] | None = None
) -> sfz.SfzCompileResult:
    return sfz.compile_instrument(
        sfz.parse(text),
        name='mapping',
        title='Mapping',
        assets={
            'sample.wav': AudioMetadata(
                channels=1,
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
    )
