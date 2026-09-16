import pytest

from ufor import synth_trace
from ufor.events import PerformanceEvent, Trigger
from ufor.instrument_trace import VoiceRetirement
from ufor.samples import trace
from ufor.samples.instrument import SampleInstrument
from ufor.synth import SynthInstrument


@pytest.mark.parametrize('kind', ['sample', 'synth'])
@pytest.mark.parametrize(
    'mode,action', [('immediate', 'stop'), ('release', 'release'), ('fade', 'fade')]
)
def test_chokes_preserve_mode_and_part(kind: str, mode: str, action: str) -> None:
    choke = {'group': 'held', 'mode': mode}
    if mode == 'fade':
        choke['fade_seconds'] = 0.25
    result = prepare(
        kind,
        [
            {
                'name': 'held',
                'choke_group': 'held',
                'mapping': {
                    'lowest_key': 60,
                    'highest_key': 60,
                    'pitch_tracking': False,
                },
            },
            {
                'name': 'choker',
                'chokes': [choke],
                'mapping': {
                    'lowest_key': 61,
                    'highest_key': 61,
                    'pitch_tracking': False,
                },
            },
        ],
        [
            Trigger(tick=0, ordinal=0, part='left', trigger_id='one', key=60),
            Trigger(tick=1, ordinal=1, part='right', trigger_id='two', key=60),
            Trigger(tick=2, ordinal=2, part='left', trigger_id='three', key=61),
        ],
    )
    retirements = [a for a in result.actions if isinstance(a, VoiceRetirement)]
    assert len(retirements) == 1
    assert retirements[0].voice_id == result.actions[0].voice_id
    assert retirements[0].action == action
    assert retirements[0].fade_seconds == (0.25 if mode == 'fade' else None)
    assert any(v.part == 'right' for v in result.snapshots[0].voices)


def prepare(
    kind: str,
    templates: list[dict[str, object]],
    events: list[PerformanceEvent],
    settings: dict[str, object] | None = None,
) -> trace.SemanticTrace | synth_trace.SemanticTrace:
    values = [
        {
            'mapping': {'lowest_key': 0, 'highest_key': 127, 'pitch_tracking': False},
            'channels': [{'input': 'mono', 'output': 'mono', 'gain': 1}],
            **v,
        }
        for v in templates
    ]
    if kind == 'synth':
        instrument = SynthInstrument.model_validate(
            {
                **(settings or {}),
                'voices': [{'oscillator': {}, **v} for v in values],
            }
        )
        return synth_trace.prepare(instrument, events, seed=42)
    instrument = SampleInstrument.model_validate(
        {
            'instrument': settings or {},
            'slices': [{'name': 'sample', 'asset': 'sample', 'end_frame': 48000}],
            'slots': [{'slice': 'sample', **v} for v in values],
        }
    )
    return trace.prepare(instrument, events, seed=42)
