"""Musical selection and traversal names used by sample instruments."""

from enum import StrEnum, auto


class Direction(StrEnum):
    forward = auto()
    backward = auto()
    mirror = auto()


class PlaybackMode(StrEnum):
    while_held = auto()
    one_shot = auto()


class LoopMode(StrEnum):
    until_release = auto()
    through_release = auto()


class TriggerKind(StrEnum):
    start = auto()
    release = auto()
    logical_release = auto()
    sustain_press = auto()
    sustain_release = auto()


class SelectionMode(StrEnum):
    cycle = auto()
    random = auto()
    shuffle = auto()


class ChokeMode(StrEnum):
    immediate = auto()
    fade = auto()
    release = auto()


class KeyBehavior(StrEnum):
    latched = auto()
    momentary = auto()


class Input(StrEnum):
    key = auto()
    velocity = auto()
    control = auto()


class FadeDirection(StrEnum):
    fade_in = 'in'
    fade_out = 'out'


class FadeCurve(StrEnum):
    linear = auto()
    equal_power = auto()
