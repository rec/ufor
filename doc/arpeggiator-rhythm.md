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


## Groove templates

Grid and Euclidean rhythms may specify `groove = [3, 1, 2, 2]`, a nonempty
list of strictly positive exact rational interval weights. The interval at
absolute step `i` is `step * len(groove) * groove[i % len(groove)] / sum(groove)`.
Each complete timing template retains `step * len(groove)` beats. On a quarter
beat grid the example intervals are 3/8, 1/8, 1/4, 1/4 beats. Starts follow those
intervals; gates multiply the resulting interval. Authored weights round-trip
without normalization in the document.

The template repeats independently of Euclidean pass length, rotation, finite
cycle limits, accent/gate lists, and note selection. Rests, rejected hits, empty
banks, and chord edits preserve phase. Seeking uses the destination's exact
rhythm position. A partial template at a finite ending is not renormalized.

Omitting `groove` retains existing swing behavior. An explicit groove requires
straight `swing = "1/2"` (the default); non-straight swing with a groove is an
error. Weights `[2, 1]` express the same timing as swing `"2/3"`. Custom/source
rhythms do not accept grooves. Groove settings are preset-only.


## Weighted transition selection

`selection = {kind = "transition", weights = [[0, 3, 1], [1, 0, 1], [4, 1, 0]]}`
selects the next entry from the row for the previously selected entry's current
rank. Rows and columns address the expanded traversal, like weighted choice;
entries retain source/layer identities. Nonnegative u32 integer weights express
relative likelihood; explicit zero forbids an edge. A nonempty table is required.
Rows may be empty or unequal in length. Missing rows/columns use `missing_weight`,
a nonnegative u32 value defaulting to 1. An explicit seed is always required.

`start = "lowest"` emits rank zero initially without consuming a transition draw;
`start = "random"` chooses uniformly with a seeded draw. When the previous entry
survives a chord edit, use its new rank. If it disappears, use the opening rule.
Bank-edit retrigger overrides preservation. Empty banks, clear, and stop forget
the previous entry; random draw counters retain their existing reset semantics.

If all weights for currently available destinations are zero, `blocked = "rest"`
(the default) emits nothing and retains the previous entry and transition draw
counter. This can remain silent until a bank edit, retrigger, or reset exposes a
path. `blocked = "uniform"` permits a uniform draw over all available entries,
including the previous entry. It deliberately relaxes zero/missing restrictions.
The first opening choice is independent of outgoing edge restrictions.

Rhythm masks, conditions, zero accents, empty banks, and rejected chance decisions
do not advance transitions. Probability is evaluated before selection, including
on a blocked opportunity. Repeats reuse one selected entry. Transition draws use
the independent `transition` random lane. Realization and selection offsets follow
selection as usual, without replacing its remembered source identity. The first
implementation supports held/latched banks and generic item banks; captured
history/phrase selection and file rendering remain unsupported.


## Interval envelopes

`selection = {kind = "interval_envelope", ranges = [{min = 1, max = 1},
{min = -2, max = 2}], boundary = "wrap"}` repeats inclusive signed rank-move
ranges. Entries refer to the expanded traversal, so this also works for opaque
nonmusical payloads. An explicit seed is required. Range endpoints are signed
64-bit integers, `min <= max`, with at most `2**64 - 1` possible moves per range.
The list is nonempty. Ranges are sampled arithmetically without enumerating moves.

The first selection is rank zero and does not apply a range or draw randomness.
Later selections use `ranges[absolute_step_index % len(ranges)]`. Every rhythm
opportunity advances this phase, including masks, rests, ties, zero accents,
blocked ranges, rejected chance, and empty banks. Repeats share one selection.
A surviving previous identity uses its current rank after edits; removal or
normal retrigger resets selection to rank zero without resetting rhythmic phase.

`boundary = "wrap"` (default) draws uniformly among inclusive signed moves,
then wraps the destination rank. Different moves may reach the same entry, so
wrapping does not deduplicate destinations. `boundary = "rest"` first intersects
the range with moves remaining inside the bank, then draws uniformly. An empty
intersection emits a rest while preserving the previous entry; the next rhythm
opportunity advances to the next range and can recover.

Draws use the `interval_envelope` lane and absolute rhythm index. Pause preserves
selection while skipping crossed opportunities; seek derives the destination
phase and uses the existing selector reset. Snapshots preserve both. Realization
and selection offsets retain their existing order. Held/latched and generic item
banks are supported; captured history/phrase selection and file rendering are
outside the first implementation.
