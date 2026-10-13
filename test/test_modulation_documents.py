import re
from pathlib import Path

from ufor.codec import parse_score, score_toml


def test_documented_modulation_examples_are_complete_documents() -> None:
    text = (Path(__file__).parents[1] / 'doc/modulation-format.md').read_text()
    examples = re.findall(r'```toml\n(.*?)```', text, re.DOTALL)
    assert examples
    for example in examples:
        document = parse_score(example)
        assert parse_score(score_toml(document)) == document
