import pytest

from ufor import sfz
from ufor.samples.enums import ChokeMode
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


@pytest.mark.parametrize('transpose', ['1.5', '128', '-128'])
def test_transpose_requires_an_in_range_integer(transpose: str) -> None:
    with pytest.raises(ValueError, match='transpose'):
        _compile(f'<region> sample=sample.wav transpose={transpose}')


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


def _compile(text: str) -> sfz.SfzCompileResult:
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
        output_channels=['mono'],
    )
