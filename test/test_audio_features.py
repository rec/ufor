import pytest
from pydantic import ValidationError

from ufor.audio_features import AudioFeatures


def test_audio_observations_reject_missing_and_non_normalized_controls() -> None:
    values = dict(level=0, bass=0, mid=0, treble=0, onset=0, beat=0, spectrum=[0, 1])
    assert AudioFeatures.model_validate(values).spectrum == [0, 1]
    for spectrum in ([], [-0.1], [1.1], [float('nan')], [float('inf')]):
        with pytest.raises(ValidationError):
            AudioFeatures.model_validate(values | {'spectrum': spectrum})
