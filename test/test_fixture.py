import pytest
from pydantic import ValidationError

from ufor.fixture import FixturePatch, FixtureScore, RawDmxCapture, patch_fixtures


def test_cues_survive_a_repatch() -> None:
    score = FixtureScore.model_validate(
        {
            'name': 'wash',
            'title': 'Wash',
            'timebase': {'name': 'seconds', 'rate': {'numerator': 1}},
            'body': {
                'profile': {
                    'name': 'wash',
                    'parameters': [
                        {
                            'name': 'intensity',
                            'unit': 'ratio',
                            'minimum': 0,
                            'maximum': 1,
                        },
                        {'name': 'gobo', 'choices': ['open', 'dots']},
                    ],
                },
                'fixtures': ['left', 'right'],
                'cues': [
                    {
                        'tick': 0,
                        'ordinal': 0,
                        'fixture': 'left',
                        'parameter': 'intensity',
                        'value': 1,
                    },
                    {
                        'tick': 5,
                        'ordinal': 1,
                        'fixture': 'right',
                        'parameter': 'gobo',
                        'value': 'dots',
                    },
                ],
            },
        }
    )
    first = patch_fixtures(
        score.body,
        [
            FixturePatch(fixture='left', universe=1, start_slot=1),
            FixturePatch(fixture='right', universe=1, start_slot=20),
        ],
    )
    second = patch_fixtures(
        score.body,
        [
            FixturePatch(fixture='left', universe=3, start_slot=42),
            FixturePatch(fixture='right', universe=4, start_slot=1),
        ],
    )
    assert score.body.cues[1].value == 'dots'
    assert first['left'].wire_universe == 0
    assert second['left'].wire_universe == 2


def test_profile_encoding_raw_capture_and_compositing_are_explicit() -> None:
    score = FixtureScore.model_validate(
        {
            'name': 'moving',
            'title': 'Moving',
            'timebase': {'name': 'seconds', 'rate': {'numerator': 1}},
            'body': {
                'profile': {
                    'name': 'moving',
                    'parameters': [
                        {'name': 'pan', 'unit': 'logical', 'minimum': 0, 'maximum': 1}
                    ],
                    'channels': [
                        {
                            'parameter': 'pan',
                            'slots': [1, 2],
                            'minimum': 0,
                            'maximum': 1,
                        }
                    ],
                    'stop': {'kind': 'fade', 'duration': 2},
                },
                'fixtures': ['left'],
                'compositors': [{'parameter': 'pan', 'rule': 'override'}],
                'cues': [
                    {
                        'tick': 0,
                        'ordinal': 0,
                        'fixture': 'left',
                        'parameter': 'pan',
                        'value': 0.2,
                        'source': 'a',
                    },
                    {
                        'tick': 0,
                        'ordinal': 1,
                        'fixture': 'left',
                        'parameter': 'pan',
                        'value': 0.8,
                        'source': 'b',
                    },
                ],
                'raw_dmx': {
                    'patch_contract': 'club-rig',
                    'synchronization': 'artnet_sync',
                    'measured_skew_ticks': 1,
                    'frames': [{'tick': 0, 'universe': 1, 'slots': [0, 255]}],
                },
            },
        }
    )
    assert score.body.profile.stop.kind == 'fade'
    with pytest.raises(ValidationError):
        RawDmxCapture(
            patch_contract='x', frames=[{'tick': 0, 'universe': 1, 'slots': [256]}]
        )
