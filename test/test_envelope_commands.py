import pytest
from pydantic import ValidationError

from ufor.events import EnvelfoChange
from ufor.instrument_trace import EnvelfoObservation


@pytest.mark.parametrize('op', [None, 'modulator'])
def test_envelope_commands_select_voice_or_operator_without_a_generator_name(
    op: str | None,
) -> None:
    event = EnvelfoChange(
        tick=0,
        ordinal=0,
        part='main',
        trigger_id='note',
        target='envelope',
        op=op,
        action='advance',
    )
    observation = EnvelfoObservation.model_validate(
        event.model_dump(exclude={'kind', 'quantize_beats'})
    )
    assert observation.target == 'envelope'
    assert observation.op == op
    assert observation.name is None


@pytest.mark.parametrize(
    'fields',
    [
        {'target': 'envelope', 'name': 'wrong'},
        {'target': 'envelfo'},
        {'name': 'vibrato', 'op': 'modulator'},
    ],
)
def test_envelope_and_generator_addresses_cannot_be_mixed(
    fields: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        EnvelfoChange.model_validate(
            {
                'tick': 0,
                'ordinal': 0,
                'part': 'main',
                'trigger_id': 'note',
                'action': 'advance',
                **fields,
            }
        )
