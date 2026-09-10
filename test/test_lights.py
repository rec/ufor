import json
from fractions import Fraction
from pathlib import Path
from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from ufor import effects, envelope, light_animation, light_math, lights, modulation
from ufor.base import Model
from ufor.codec import parse_score, score_toml
from ufor.composition import Composition, ScoreRecord
from ufor.control import Scope
from ufor.interface import (
    LightBinding,
    Output,
    OutputSelection,
    ParameterExport,
    Part,
    ScoreVersion,
)
from ufor.lfo import LFO, Reset
from ufor.time import Rate, Timebase


def score(
    operation: Model,
    components: list[str] | None = None,
    layout: lights.Layout | None = None,
    parts: list[Part] | None = None,
) -> light_animation.AnimationScore:
    return light_animation.AnimationScore(
        name='test',
        title='Test',
        timebases=[Timebase(name='frames', rate=Rate(numerator=20))],
        outputs=[
            Output(
                name='light',
                stream=lights.LightType(
                    timebase='frames',
                    components=components or ['red', 'green', 'blue'],
                    layout=layout or lights.strip(2),
                ),
                binding=LightBinding(),
            )
        ],
        body=light_animation.Animation(operation=operation, parts=parts or []),
    )


def selection(name: str = 'child') -> OutputSelection:
    return OutputSelection(name=name, output='light')


def part(name: str = 'child') -> Part:
    return Part(name=name, score=ScoreVersion(path=f'{name}.toml'))


@pytest.mark.parametrize(
    'components',
    [
        ['white'],
        ['warm', 'cool'],
        ['red', 'green', 'blue'],
        ['red', 'green', 'blue', 'white'],
        ['red', 'green', 'blue', 'amber', 'white'],
    ],
)
def test_all_component_counts_round_trip_and_compose(components: list[str]) -> None:
    fill = light_animation.Fill(values=[0.25] * len(components))
    document = score(fill, components)
    assert parse_score(score_toml(document)) == document
    output = document.outputs[0].stream
    assert isinstance(output, lights.LightType)
    frame = light_math.compose_frame(fill, output, {})
    assert len(frame) == 2 and all(r == fill.values for r in frame)
    gain = light_animation.Gain(source=selection(), amount=2)
    assert all(
        r == [0.5] * len(components)
        for r in light_math.compose_frame(gain, output, {selection(): frame})
    )


@pytest.mark.parametrize('effect', get_args(get_args(effects.EffectValue)[0]))
def test_every_extracted_effect_has_a_portable_valid_default(
    effect: type[effects.Effect],
) -> None:
    value = effect()
    document = score(value)
    assert parse_score(score_toml(document)) == document
    assert (
        TypeAdapter(effects.EffectValue).validate_json(value.model_dump_json()) == value
    )


def test_serpentine_wiring_preserves_logical_geometry() -> None:
    fixture = json.loads(Path('conformance/lights/layouts.json').read_text())
    layout = lights.matrix(3, 2)
    assert layout.model_dump(mode='json') == fixture['matrix']
    wiring = lights.serpentine(3, 2)
    assert wiring.indexes(layout) == fixture['serpentine_indexes']
    assert (
        light_math.wire_frame(fixture['logical_frame'], layout, wiring)
        == fixture['physical_frame']
    )
    assert [p.position for p in layout.lights] == fixture['positions']


def test_rings_and_irregular_geometry_do_not_require_a_matrix() -> None:
    layout = lights.rings([4, 8], [1, 2])
    assert len(layout.lights) == 12
    assert len(layout.regions['ring_1']) == 8
    assert layout.lights[0].position == [1, 0]
    irregular = lights.Layout(
        name='sculpture',
        axes=['x', 'y', 'z'],
        unit='metres',
        lights=[lights.Light(name='tip', position=[0.2, 0.7, 1.3])],
    )
    assert irregular.lights[0].name == 'tip'


@pytest.mark.parametrize(
    'order', [['light_0', 'light_0'], ['light_0'], ['light_0', 'missing']]
)
def test_wiring_rejects_missing_and_repeated_lights(order: list[str]) -> None:
    with pytest.raises(ValueError, match='permutation'):
        lights.Wiring(order=order).indexes(lights.strip(2))


def test_layout_rejects_invalid_coordinates_and_regions() -> None:
    data = lights.strip(2).model_dump()
    data['axes'] = ['x', 'y']
    with pytest.raises(ValidationError, match='positions'):
        lights.Layout.model_validate(data)
    data = lights.strip(2).model_dump() | {'regions': {'missing': ['absent']}}
    with pytest.raises(ValidationError, match='known'):
        lights.Layout.model_validate(data)


def test_rgb_effects_do_not_invent_white_channels_or_linear_light() -> None:
    with pytest.raises(ValidationError, match='RGB effects'):
        score(effects.Aurora(), ['red', 'green', 'blue', 'white'])
    document = score(effects.Aurora()).model_dump()
    document['outputs'][0]['stream']['interpretation'] = 'linear_srgb'
    with pytest.raises(ValidationError, match='drive'):
        light_animation.AnimationScore.model_validate(document)


def test_mix_clips_each_boundary_but_crossfade_and_gain_preserve_range() -> None:
    output = score(light_animation.Fill(values=[1]), ['white']).outputs[0].stream
    assert isinstance(output, lights.LightType)
    mix = light_animation.Mix(
        sources=[light_animation.WeightedSource(source=selection(), weight=2)]
    )
    clipped = light_math.compose_frame(mix, output, {selection(): [[1], [1]]})
    nested = light_math.compose_frame(
        light_animation.Mix(
            sources=[light_animation.WeightedSource(source=selection(), weight=0.5)]
        ),
        output,
        {selection(): clipped},
    )
    assert nested == [[0.5], [0.5]]
    fade = light_animation.Crossfade(
        outgoing=selection('a'),
        incoming=selection('b'),
        fade=light_animation.Fade(duration=1),
    )
    assert light_math.compose_frame(
        fade,
        output,
        {selection('a'): [[2], [2]], selection('b'): [[4], [4]]},
        Fraction(1, 2),
    ) == [[3], [3]]


def test_placement_supports_arbitrary_named_regions_and_component_maps() -> None:
    output = (
        score(
            light_animation.Fill(values=[0, 0]), ['warm', 'cool'], lights.matrix(2, 2)
        )
        .outputs[0]
        .stream
    )
    assert isinstance(output, lights.LightType)
    place = light_animation.Place(
        placements=[
            light_animation.Placement(source=selection(), lights=['light_3', 'light_0'])
        ]
    )
    frame = light_math.compose_frame(
        place, output, {selection(): [[0.25, 0.5], [0.5, 1]]}
    )
    assert frame == [[0.5, 1], [0, 0], [0, 0], [0.25, 0.5]]
    mapping = light_animation.ComponentMap(source=selection(), matrix=[[1], [0.5]])
    assert light_math.compose_frame(
        mapping, output, {selection(): [[1], [0], [0], [0]]}
    )[0] == [1, 0.5]


def test_cues_start_local_clocks_and_do_not_require_inactive_frames() -> None:
    cues = light_animation.Cues(
        cues=[
            light_animation.Cue(source=selection('a'), start='1/2', duration=1),
            light_animation.Cue(source=selection('b'), start=1, duration=1),
        ]
    )
    assert light_animation.cue_weights(cues, Fraction(0)) == []
    assert light_animation.cue_weights(cues, Fraction(1, 2)) == [
        (selection('a'), Fraction(0), 1)
    ]
    assert light_animation.cue_weights(cues, Fraction(5, 4)) == [
        (selection('a'), Fraction(3, 4), 0.5),
        (selection('b'), Fraction(1, 4), 0.5),
    ]
    document = score(cues, ['white'], parts=[part('a'), part('b')])
    output = document.outputs[0].stream
    assert isinstance(output, lights.LightType)
    assert light_math.compose_frame(cues, output, {}, Fraction(0)) == [[0], [0]]
    child = score(light_animation.Fill(values=[1]), ['white'])
    composition = Composition(
        'main',
        {
            'main': ScoreRecord(
                score=document, paths={'a.toml': 'child', 'b.toml': 'child'}
            ),
            'child': ScoreRecord(score=child),
        },
    )
    assert composition.evaluation_windows(25, 30) == {
        ('root', 'light'): (25, 30),
        ('root/a', 'light'): (0, 20),
        ('root/b', 'light'): (0, 10),
    }


def test_shared_curves_allow_repeating_gain_above_one() -> None:
    curve = envelope.Curve(
        initial=0, segments=[envelope.Segment(duration=1, target=2)], repeat=True
    )
    assert envelope.curve_at(curve, Fraction(1, 2)) == 1
    assert envelope.curve_at(curve, Fraction(1)) == 0
    assert envelope.curve_at(curve, Fraction(7, 4)) == 1.5
    with pytest.raises(ValidationError, match='levels'):
        envelope.Envelope(
            segments=curve.segments, release=[envelope.Segment(duration=1, target=0)]
        )


def test_light_parameters_use_existing_exports_and_modulation() -> None:
    target = modulation.Target(name='animation', parameter='amount')
    body = light_animation.Animation(
        operation=light_animation.Gain(source=selection()),
        parts=[part()],
        modulation=modulation.Modulation(
            parameters=[
                modulation.Parameter(
                    target=target,
                    unit=modulation.Unit.ratio,
                    scope=Scope.part,
                    minimum=0,
                    maximum=3,
                    default=1,
                )
            ]
        ),
    )
    document = score(body.operation, ['white'], parts=body.parts)
    document = light_animation.AnimationScore.model_validate(
        document.model_dump()
        | {
            'body': body,
            'parameters': [ParameterExport(name='brightness', binding=target)],
        }
    )
    child = score(light_animation.Fill(values=[1]), ['white'])
    composition = Composition(
        'main',
        {
            'main': ScoreRecord(score=document, paths={'child.toml': 'child'}),
            'child': ScoreRecord(score=child),
        },
        {'brightness': 2},
    )
    assert composition.parts['root'].parameters == {'brightness': 2}
    assert light_animation.operation_at(
        body, Fraction(0), {'amount': 2}
    ) == light_animation.Gain(source=selection(), amount=2)
    sample = light_animation.control_value(
        light_animation.Control(
            name='pulse', curve=LFO(rate=1, delay=1, scope=Scope.part, reset=Reset.free)
        ),
        Fraction(0),
    )
    assert sample.weight == 0


def test_light_composition_rejects_implicit_component_conversion() -> None:
    document = score(
        light_animation.Reverse(source=selection()), ['white'], parts=[part()]
    )
    child = score(light_animation.Fill(values=[0, 0]), ['warm', 'cool'])
    with pytest.raises(ValueError):
        Composition(
            'main',
            {
                'main': ScoreRecord(score=document, paths={'child.toml': 'child'}),
                'child': ScoreRecord(score=child),
            },
        )


def test_language_neutral_composition_vectors() -> None:
    cases = json.loads(Path('conformance/lights/operations.json').read_text())['cases']
    for case in cases:
        names = [f['name'] for f in case['frames']]
        template = score(light_animation.Fill(values=[0]), ['white'])
        data = template.model_dump()
        data['outputs'][0]['stream']['components'] = case['components']
        data['body'] = {
            'operation': case['operation'],
            'parts': [part(n).model_dump() for n in names],
        }
        document = light_animation.AnimationScore.model_validate(data)
        output = document.outputs[0].stream
        assert isinstance(output, lights.LightType)
        frames = {selection(f['name']): f['values'] for f in case['frames']}
        result = light_math.compose_frame(
            document.body.operation, output, frames, Fraction(case.get('at', '0'))
        )
        assert result == case['expected'], case['name']


def test_complete_mirrored_cues_example_and_shared_controls() -> None:
    records = {}
    for path in Path('conformance/lights').glob('*.toml'):
        document = parse_score(path.read_text())
        assert isinstance(document, light_animation.AnimationScore)
        assert parse_score(score_toml(document)) == document
        records[path.stem] = ScoreRecord(
            score=document,
            paths={p.score.path: Path(p.score.path).stem for p in document.body.parts},
        )
    composition = Composition('brightness', records, {'brightness': 2})
    assert composition.extent('root', 'light') == (0, 200)
    assert (
        composition.parts['root/main/limbs/ripples'].score
        == composition.parts['root/main/limbs/mirror/ripples'].score
    )
    windows = composition.evaluation_windows(90, 100)
    assert windows['root/main/aurora', 'light'] == (0, 20)
    assert windows['root/main/limbs/mirror/ripples', 'light'] == (0, 100)
    body = records['brightness'].score.body
    assert isinstance(body, light_animation.Animation)
    operation = light_animation.operation_at(body, Fraction(1, 2), {'amount': 2})
    assert isinstance(operation, light_animation.Gain)
    assert operation.amount == 1


def test_cue_boundaries_require_exact_ticks_and_unique_parts() -> None:
    with pytest.raises(ValidationError, match='exact logical ticks'):
        score(
            light_animation.Cues(
                cues=[light_animation.Cue(source=selection(), start='1/3', duration=1)]
            ),
            parts=[part()],
        )
    with pytest.raises(ValidationError, match='cue part'):
        light_animation.Cues(
            cues=[
                light_animation.Cue(source=selection(), start=0, duration=1),
                light_animation.Cue(source=selection(), start=1, duration=1),
            ]
        )


def test_documented_multicomponent_score_round_trips() -> None:
    text = (
        Path('doc/light-format.md')
        .read_text()
        .split('```toml\n', 1)[1]
        .split('```', 1)[0]
    )
    document = parse_score(text)
    assert isinstance(document, light_animation.AnimationScore)
    assert parse_score(score_toml(document)) == document
    ring = lights.Layout.model_validate_json(
        Path('conformance/lights/rings.json').read_text()
    )
    assert ring == lights.rings([4, 8], [1, 2])
