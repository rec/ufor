from ufor.interface import ScoreReference
from ufor.preset import PresetScore


class LocalPreset(PresetScore):
    name: str = 'Python preset'
    title: str = 'Python preset'
    score: ScoreReference = ScoreReference(selector='Python triangle')
