# Arpeggiator Motion ports

`ufor.arpeggiator_ports` defines a portable control payload and output batch.
The host timestamps each control in the arpeggiator's running beat coordinate.
Equal-time input controls precede an unprocessed step; the latest value per port
wins before publication. A host seek cancels pending controls. Pause retains them.

Inputs:

- `gate`: nonnegative exact rational gate fraction, initially the preset gate.
- `density`: exact rational hit probability in [0, 1], initially the preset
  probability. Fractional density requires an explicit preset seed and uses
  arpeg's existing named probability draw contract. Rejected hits do not advance
  note selection. Density replaces the preset probability rather than multiplying it.
- `transposition`: signed 64-bit whole semitones, initially the preset's
  `body.transposition.semitones` (default 0). Fractional offsets are rejected.
  `body.transposition.boundary` is `drop` by default, or `fold` or `error`.
  Drop skips the selected note and emits rest while advancing selection. Fold
  shifts only out-of-range pitches by the fewest octaves needed to enter MIDI
  0–127. Error reports an out-of-range selected pitch to the caller.
  Source pitches and identities remain unchanged. Transposition is fixed when
  the step is admitted, including all its repeats; sounding notes retain it.

Outputs carry exact beat `at`, zero-based rhythm `index`, and bank `revision`.
At each scheduled opportunity emit `step`, followed by `hit` if a source note
was admitted, otherwise `rest`. Ties emit only `step`. Repeated attacks from one
hit share one `hit` event. Gates and expression mappings already realized for
sounding notes or pending repeats remain unchanged by subsequent controls.

The output batch contains at most 4096 events. Reserve two event slots before
admitting a step. If full, skip new step admissions and keep executing owned
releases; draining the batch reports `exhausted = true` and permits subsequent
steps. No skipped attacks are replayed. Hosts drain after each operation.

These ports do not execute a Motion graph. The host owns graph evaluation and
ordering, applies scalar samples before the target step, and routes output
events after collecting them. Feedback must arrive at a later opportunity with
an explicit delay of at least one scheduling quantum and a bounded event budget.
