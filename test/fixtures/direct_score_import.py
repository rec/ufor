"""Run in a fresh interpreter to exercise recursive model initialization."""

import sys


def check_import() -> None:
    mode, operation = sys.argv[1:]
    if mode in ('part', 'inline'):
        from ufor.interface import Part

        model = Part
        data = {'name': 'child', 'score': {'path': 'child.toml'}}
        if mode == 'inline':
            data['score'] = {
                'kind': 'arrangement',
                'name': 'mix',
                'title': 'Mix',
                'timebases': [{'name': 'audio', 'rate': {'numerator': 48000}}],
                'body': {
                    'timebase': 'audio',
                    'parts': [
                        {
                            'name': 'scale',
                            'score': {
                                'kind': 'scale',
                                'name': 'scale',
                                'title': 'Scale',
                                'body': {},
                            },
                        }
                    ],
                },
            }
    elif mode == 'arrangement':
        from ufor.arrangement import Arrangement

        model = Arrangement
        data = {
            'timebase': 'audio',
            'parts': [{'name': 'child', 'score': {'path': 'child.toml'}}],
        }
    elif mode == 'animation':
        from ufor.light_animation import Animation

        model = Animation
        data = {'operation': {'effect': 'fill', 'values': [1]}}
    elif mode == 'animation_score':
        from ufor.light_animation import AnimationScore
        from ufor.lights import strip

        model = AnimationScore
        data = {
            'name': 'light',
            'title': 'Light',
            'timebases': [{'name': 'frames', 'rate': {'numerator': 60}}],
            'outputs': [
                {
                    'name': 'main',
                    'stream': {
                        'family': 'sampled',
                        'timebase': 'frames',
                        'components': ['white'],
                        'layout': strip(1).model_dump(),
                    },
                    'binding': {'light': True},
                }
            ],
            'body': {'operation': {'effect': 'fill', 'values': [1]}},
        }
    else:
        from ufor.arrangement import ArrangementScore

        model = ArrangementScore
        data = {
            'name': 'mix',
            'title': 'Mix',
            'timebases': [{'name': 'audio', 'rate': {'numerator': 48000}}],
            'body': {
                'timebase': 'audio',
                'parts': [{'name': 'child', 'score': {'path': 'child.toml'}}],
            },
        }
    assert 'ufor.codec' not in sys.modules
    if operation == 'schema':
        assert model.model_json_schema()
    elif operation == 'validate':
        assert model.model_validate(data)
    else:
        assert model(**data)
    assert 'ufor.codec' not in sys.modules


if __name__ == '__main__':
    check_import()
