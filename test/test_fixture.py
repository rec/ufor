from ufor.fixture import FixturePatch, FixtureScore, patch_fixtures


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
