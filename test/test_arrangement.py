import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.arrangement import ArrangementDocument
from ufor.codec import document_toml, parse_document
from ufor.streams import AudioType


def test_documented_arrangement_separates_ports_from_destinations() -> None:
    path = Path(__file__).parents[1] / 'doc/arrangement-format.md'
    text = re.search(r'```toml\n(.*?)```', path.read_text(), re.DOTALL)
    assert text is not None
    document = parse_document(text[1])
    assert document.body.outputs[0].id == document.destinations[0].port
    assert 'path' not in document.body.outputs[0].model_dump()
    assert parse_document(document_toml(document)) == document
    assert ArrangementDocument.model_json_schema()['properties']['body']


def test_audio_ports_reject_other_quantities_and_duplicate_channels() -> None:
    with pytest.raises(ValidationError):
        AudioType.model_validate(
            {'timebase': 'audio', 'channels': ['left'], 'quantity': 'voltage'}
        )
    with pytest.raises(ValidationError, match='duplicate'):
        AudioType(timebase='audio', channels=['left', 'left'])
