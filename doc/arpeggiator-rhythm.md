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
