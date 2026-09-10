from ufor.interface import ScoreVersion
from ufor.preset import PresetScore


class LocalPreset(PresetScore):
    name: str = 'Python preset'
    title: str = 'Python preset'
    score: ScoreVersion = ScoreVersion(selector='Python triangle')
