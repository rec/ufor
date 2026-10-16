# Arpeggiator swing

Grid and Euclidean rhythms accept `swing`, an exact rational first-interval
share of a two-step pair. It defaults to `"1/2"` (straight timing), must be at
least one half, and must be less than one. `"2/3"` gives a 2:1 pair. Custom
patterns and source rhythms do not accept this field.

For straight step duration `d` and share `s`, pair `k` begins at `2*k*d`.
Its second opportunity is at `2*k*d + 2*d*s`; the next pair starts at
`2*(k+1)*d`. The first interval is `2*d*s` and the second is `2*d*(1-s)`.
Gate lengths use the interval after the swung start times have been established.

Pair phase follows the absolute local step index, including rests, rejected
chance decisions, and empty banks. Euclidean rotation affects its hit mask;
it does not reset swing. Odd-length Euclidean loops alternate their swing
alignment. Chord edits do not reset rhythm phase. Transport seeks find the
first swung opportunity at or after the target beat without replaying earlier
opportunities. Swing is preset-only; there is no live swing control port.

## Accent and gate patterns

An optional `body.patterns` table supplies independent nonempty lists of exact,
nonnegative multipliers: `accents` and `gates`. Each omitted list defaults to
`[1]`. Omitting the table preserves the source velocity and ordinary gate.

Lists index the absolute local rhythm step, including rests, rejected chance,
empty banks, and ties, and loop independently. Chord edits do not reset phase;
seeks use the target rhythm position. Repeats reuse their parent step's values.
A zero accent rejects a new start before chance or selection, without cancelling
already sounding occurrences. Untied zero-gate hits still create an immediate start/end.

Gates multiply the current global gate after start times are established. Tie
lookahead uses the multiplier at each tied cell to find the final release; ties
retain the originating accent and never create a new start. Already scheduled
repeats and ties keep their realized settings when controls or banks change.

MIDI adapters multiply source attack velocity, round halves upward, and clamp
positive results to 1–127. Release velocity, raw source events, and breath,
bend, and pressure values are retained. Generic occurrences carry the exact
accent multiplier without interpreting the payload. These lists are preset-only.


## Conditional hits

A custom hit cell may include `condition = {passes = [1, 3], out_of = 4}`.
Passes are numbered from 1 and repeat after `out_of` complete rhythm-pattern
passes. The list must be nonempty, contain unique positive integers, and not
exceed the positive integer `out_of`. Omission admits the hit on every pass.
Only hit cells accept conditions.

For absolute cell index `i` and pattern length `n`, the current pass is
`(i // n) % out_of + 1`. All cells, silent passes, empty banks, and chord edits
retain this rhythm phase. Seeking derives it from the target transport position.
A failed condition acts as a rest before probability and selection, consuming
neither a chance draw nor a selected note. Accent and gate lists keep advancing.
Repeats share the hit's condition result. Admitted hits sustain through following
ties, including ties across a pass boundary; skipped hits start no occurrence
for those ties to extend. Conditions do not cut off previously scheduled notes.

## Finite rhythm passes

Custom patterns and Euclidean rhythms may specify `cycles = N`, a strictly
positive integer. Omission loops indefinitely. A custom pass contains every
cell in `steps`, including rests and ties; a Euclidean pass contains its declared
number of steps, independent of rotation, pulses, and swing. Plain grids and
source rhythms do not accept this setting.

Passes follow absolute transport position and include silent or empty-bank
passes. Chord edits do not restart the allowance. Seeking before the ending
makes the corresponding passes available; seeking to or beyond it admits no
hits. Conditional pass counters retain their existing transport phase.

At the limit no further attacks or cycle-start notifications are generated.
The underlying step clock and controls continue. Already scheduled attacks and
gates complete normally, including gates beyond the ending. Tie lookahead stops
before cells in unplayed passes. Stop, pause, and seek retain their existing
cleanup semantics; pausing does not renew the allowance.
