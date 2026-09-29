import math
from fractions import Fraction

type NoteNumber = int  # May be negative
type PitchNumber = float | int | Fraction


def cents_to_ratio(f: PitchNumber) -> float:
    return math.exp2(float(f) / 1200)


def ratio_to_cents(c: PitchNumber) -> float:
    return math.log2(float(c)) * 1200
