"""Regenerate scores.json from the installed uFor models."""

import json
from pathlib import Path

from ufor.codec import score_schema


def generate() -> None:
    destination = Path(__file__).with_name('scores.json')
    destination.write_text(json.dumps(score_schema(), indent=2) + '\n')


if __name__ == '__main__':
    generate()
