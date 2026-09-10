from ufor.musical import OscillatorScore
from ufor.oscillator import Oscillator


class LocalOscillator(OscillatorScore):
    name: str = 'Python triangle'
    title: str = 'Python triangle'
    tags: list[str] = ['#python', '#tone']
    body: Oscillator = Oscillator()

    def __init__(self, **data: object) -> None:
        raise AssertionError('library indexing must not invoke the score constructor')

    def render(self) -> None:
        raise AssertionError('library indexing must not render')
