from ufor.references import RecordSelector


def test_structured_selectors_preserve_punctuation() -> None:
    selector = RecordSelector(source='rack:one', track='mic:2', channel=0)
    assert RecordSelector.model_validate_json(selector.model_dump_json()) == selector
