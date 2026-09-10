from ufor.musical import OscillatorScore
from ufor.oscillator import Oscillator


class Tone(OscillatorScore):
    name: str = 'triangle tone'
    title: str = 'A triangle oscillator'
    tags: list[str] = ['#tone']
    body: Oscillator = Oscillator()
