import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    'model', ['part', 'inline', 'arrangement', 'score', 'animation', 'animation_score']
)
@pytest.mark.parametrize('operation', ['construct', 'validate', 'schema'])
def test_recursive_models_work_without_codec(model: str, operation: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parent / 'fixtures/direct_score_import.py'),
            model,
            operation,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
