from fractions import Fraction

import pytest
from pydantic import TypeAdapter, ValidationError

from ufor.envelfo import (
    LFO,
    EnveLFO,
    EnveLFOReference,
    Envelope,
    Generator,
    Patch,
    Stages,
)


def test_concrete_generators_are_flat_envelfos() -> None:
    value = LFO(rate='2 Hz', scope='instrument')
    assert isinstance(value, EnveLFO)
    assert value.rate == 2
    assert 'body' not in value.model_dump()
    assert TypeAdapter(Generator).validate_json(value.model_dump_json()) == value


def test_nested_generators_inherit_the_parent_clock_and_scope() -> None:
    patch = Patch.model_validate(
        {
            'clock': 'beats',
            'scope': 'instrument',
            'envelfos': {
                'gesture': {
                    'kind': 'stages',
                    'initial_stage': 'attack',
                    'stages': [
                        {
                            'name': 'attack',
                            'envelfo': {
                                'kind': 'envelope',
                                'segments': [{'duration': '1/3 beat', 'to': 1}],
                            },
                        }
                    ],
                }
            },
            'outputs': {'value': 'gesture'},
        }
    )
    stages = patch.envelfos['gesture']
    assert isinstance(stages, Stages)
    envelope = stages.stages[0].envelfo
    assert isinstance(envelope, Envelope)
    assert stages.clock == envelope.clock == patch.clock
    assert stages.scope == envelope.scope == patch.scope
    assert envelope.segments[0].duration == Fraction(1, 3)
    data = patch.model_dump()
    assert 'clock' not in data['envelfos']['gesture']
    assert 'scope' not in data['envelfos']['gesture']['stages'][0]['envelfo']
    assert Patch.model_validate_json(patch.model_dump_json()) == patch


@pytest.mark.parametrize('override', [{'clock': 'seconds'}, {'scope': 'voice'}])
def test_patch_children_cannot_override_even_matching_parent_settings(
    override: dict[str, str],
) -> None:
    with pytest.raises(ValidationError, match='overrides are not allowed'):
        Patch.model_validate(
            {
                'envelfos': {'wave': {'kind': 'lfo', 'rate': 1} | override},
                'outputs': {'value': 'wave'},
            }
        )


def test_library_references_are_distinct_from_concrete_generators() -> None:
    reference = EnveLFOReference(score={'selector': 'vibrato'}, parameters={'speed': 4})
    assert isinstance(reference, EnveLFO)
    assert reference.kind == 'reference'
    assert 'body' not in reference.model_dump()
    assert (
        TypeAdapter(Generator).validate_json(reference.model_dump_json()) == reference
    )
