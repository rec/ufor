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
