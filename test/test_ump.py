import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.events import UmpEvent
from ufor.sequence import Sequence


def test_ump_portable_conformance() -> None:
    cases = json.loads(Path('conformance/ump.json').read_text())
    for case in cases['valid']:
        packet = UmpEvent(tick=0, ordinal=0, words=case['words'])
        assert packet.message_type == case['message_type']
        assert packet.group == case['group']
        assert packet.sysex_format == case['sysex_format']
        source = Sequence(timebase='clock', end=1, events=[packet])
        assert Sequence.model_validate_json(source.model_dump_json()) == source
    for words in cases['invalid']:
        with pytest.raises(ValidationError):
            UmpEvent(tick=0, ordinal=0, words=words)


@pytest.mark.parametrize(
    'message_type,count',
    list(enumerate([1, 1, 1, 2, 2, 4, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4])),
)
def test_every_packet_size_including_unknown_types(
    message_type: int, count: int
) -> None:
    words = [message_type << 28] + [0] * (count - 1)
    assert UmpEvent(tick=0, ordinal=0, words=words).words == words
