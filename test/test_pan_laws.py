import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.samples.instrument import SampleInstrument
from ufor.samples.processing import PanLaw, pan_gains


@pytest.mark.parametrize(
    ('law', 'stereo', 'position', 'gains'),
    [
        (c['law'], c['stereo'], c['position'], c['gains'])
        for c in json.loads(Path('conformance/pan-laws.json').read_text())['cases']
    ],
)
def test_pan_laws_match_portable_examples(
    law: str, stereo: bool, position: float, gains: list[float]
) -> None:
    assert pan_gains(position, PanLaw(law), stereo=stereo) == pytest.approx(
        gains, abs=1e-14
    )


def test_pan_law_defaults_and_round_trips_per_instrument() -> None:
    raw = json.loads(Path('conformance/instrument.json').read_text())['body']
    raw.pop('pan_law')
    assert SampleInstrument.model_validate(raw).pan_law == PanLaw.native
    raw['pan_law'] = 'sfizz'
    instrument = SampleInstrument.model_validate(raw)
    assert (
        SampleInstrument.model_validate_json(instrument.model_dump_json()).pan_law
        == PanLaw.sfizz
    )
    raw['pan_law'] = 'unknown'
    with pytest.raises(ValidationError):
        SampleInstrument.model_validate(raw)


@pytest.mark.parametrize('position', [-1.01, 1.01, float('nan'), float('inf')])
def test_pan_laws_reject_out_of_range_positions(position: float) -> None:
    with pytest.raises(ValueError, match='pan position'):
        pan_gains(position, PanLaw.native, stereo=False)
