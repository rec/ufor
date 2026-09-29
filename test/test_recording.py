import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.assets import (
    Asset,
    ContentIdentity,
    PythonProviderLocation,
    RelativeFileLocation,
    StreamLocation,
)
from ufor.codec import parse_score, score_toml
from ufor.recording import (
    AudioFragment,
    AudioStream,
    EventStream,
    Gap,
    Recording,
    RecordingScore,
    UnmappedAudioFragment,
    stream_outputs,
)
from ufor.streams import AudioType
from ufor.time import Rate, Timebase


def recording() -> RecordingScore:
    return RecordingScore(
        name='session',
        title='Session',
        assets=[
            Asset(
                name=i,
                location=RelativeFileLocation(path=f'{i}.wav'),
                encoding='wav',
                content=ContentIdentity(byte_length=1, sha256='0' * 64),
            )
            for i in ('journal', 'take')
        ],
        timebases=[Timebase(name='audio', rate=Rate(numerator=48000))],
        body=Recording(
            state='sealed',
            started_at='2026-09-04T12:00:00Z',
            ended_at='2026-09-04T12:00:03Z',
            journal='journal',
            streams=[
                AudioStream(
                    name='desk',
                    source_id='audio:desk',
                    end=144000,
                    stream=AudioType(timebase='audio', channels=['left']),
                    fragments=[AudioFragment(asset='take', start=48000, count=48000)],
                    gaps=[
                        Gap(start=0, end=48000, reason='unknown'),
                        Gap(start=96000, end=144000, reason='input_overflow'),
                    ],
                )
            ],
        ),
    )


def test_recording_round_trip_preserves_gaps_and_native_counts() -> None:
    value = recording()
    assert parse_score(score_toml(value)) == value
    stream = value.body.streams[0]
    assert isinstance(stream, AudioStream)
    assert stream.end == 144000
    assert sum(f.count for f in stream.fragments) == 48000


def test_recording_round_trip_preserves_project_name() -> None:
    value = recording()
    value = value.model_copy(
        update={'body': value.body.model_copy(update={'project_name': 'x18-show'})}
    )

    assert parse_score(score_toml(value)).body.project_name == 'x18-show'


def test_recording_rejects_unknown_assets() -> None:
    data = recording().model_dump()
    data['assets'] = data['assets'][:1]
    with pytest.raises(ValidationError, match='unknown asset'):
        RecordingScore.model_validate(data)


@pytest.mark.parametrize(
    'location',
    [
        StreamLocation(url='https://example.org/live', transport='icecast'),
        PythonProviderLocation(module='audio', function='source', delivery='buffer'),
    ],
)
def test_sealed_recording_rejects_live_assets(location: object) -> None:
    data = recording().model_dump()
    data['assets'][1] = {
        'name': 'take',
        'location': location,
        'encoding': 'float32',
    }
    with pytest.raises(ValidationError, match='finite assets'):
        RecordingScore.model_validate(data)


def test_open_recording_allows_live_asset_declarations() -> None:
    data = recording().model_dump()
    data['body']['state'] = 'open'
    data['body']['ended_at'] = None
    data['assets'][1] = {
        'name': 'take',
        'location': StreamLocation(url='https://example.org/live', transport='icecast'),
        'encoding': 'float32',
    }
    assert RecordingScore.model_validate(data).body.state == 'open'


def test_native_lfo_change_stream_can_be_exported() -> None:
    stream = EventStream(
        name='lfo',
        source_id='controls',
        event_schema='recs_events',
        event_kind='lfo_change',
        timebase='ticks',
    )
    score = RecordingScore(
        name='changes',
        title='LFO changes',
        assets=[],
        timebases=[Timebase(name='ticks', rate=Rate(numerator=48000))],
        outputs=stream_outputs([stream]),
        body=Recording(state='sealed', streams=[stream]),
    )
    assert parse_score(score_toml(score)) == score


def test_gap_cannot_cover_recorded_audio() -> None:
    stream = recording().body.streams[0]
    data = stream.model_dump()
    data['gaps'] = [{'start': 0, 'end': 96000, 'reason': 'unknown'}]
    with pytest.raises(ValidationError, match='overlaps'):
        AudioStream.model_validate(data)


def test_many_alternating_audio_fragments_and_gaps_cover_extent() -> None:
    stream = AudioStream(
        name='desk',
        source_id='audio:desk',
        stream=AudioType(timebase='audio', channels=['left']),
        end=4000,
        fragments=[
            AudioFragment(asset='take', start=2 * i, count=1) for i in range(2000)
        ],
        gaps=[
            Gap(start=2 * i + 1, end=2 * i + 2, reason='unknown') for i in range(2000)
        ],
    )
    assert stream.end == 4000


def test_gap_cannot_overlap_unmapped_audio() -> None:
    with pytest.raises(ValidationError, match='overlaps captured audio'):
        AudioStream(
            name='desk',
            source_id='audio:desk',
            stream=AudioType(timebase='audio', channels=['left']),
            end=10,
            unmapped_fragments=[
                UnmappedAudioFragment(
                    asset='take', count=10, journal_range={'start': 0, 'end': 10}
                )
            ],
            gaps=[Gap(start=2, end=4, reason='unknown')],
        )


def test_unrecorded_intervals_need_explicit_gaps() -> None:
    data = recording().body.streams[0].model_dump()
    data['gaps'] = []
    with pytest.raises(ValidationError, match='explicit gaps'):
        AudioStream.model_validate(data)


def test_documented_recording_and_sequence_examples_round_trip() -> None:
    path = Path(__file__).parents[1] / 'doc/recording-format.md'
    examples = re.findall(r'```toml\n(.*?)```', path.read_text(), re.DOTALL)
    assert len(examples) == 2
    for example in examples:
        value = parse_score(example)
        assert parse_score(score_toml(value)) == value


@pytest.mark.parametrize('schema, kind', [('midi', 'trigger'), ('osc', 'midi')])
def test_event_stream_rejects_contradictory_payload_kind(
    schema: str, kind: str
) -> None:
    from ufor.recording import EventStream

    with pytest.raises(ValueError, match='event kind'):
        EventStream(
            name='events', source_id='input', event_schema=schema, event_kind=kind
        )
