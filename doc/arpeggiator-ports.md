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

- `selection_offset`: signed 64-bit whole ascending-pitch ranks, initially
  `body.selection_offset.ranks` (default 0). Equal pitches use source identity
  to break ties. The selector advances using its original choice, then the
  offset selects a target from the current bank. Output uses the target's
  identity, velocity, and recorded expression, followed by pitch transposition.
  `body.selection_offset.boundary` defaults to `wrap`; `rest` skips targets
  outside the bank. Skips advance the selector and emit rest. Density rejection
  and rhythm rests still leave the selector untouched. Repeats retain one target.

Outputs carry exact beat `at`, zero-based rhythm `index`, and bank `revision`.
Expression controls are realized by the MIDI player, rather than queued by the
pure step engines. `breath` and `pressure` accept exact normalized values in
[0, 1]; `bend` accepts [-1, 1], the wheel position rather than a musical interval.
`body.expression.lanes` chooses `current`, `recorded`, or `motion` per named lane.
Unspecified lanes inherit `body.expression.source`. Held/latched banks cannot
provide recorded lanes. A Motion sample requires the lane to declare `motion`.
It immediately affects an owned sounding note, or is held during rests/pauses
for the next onset. Samples survive pause, clear, and transport relocation.
They remain distinct from the received MIDI capture ledger and current state.
Unseen values are not initialized. Source combinations are not implemented.

Normalize CC2 and channel pressure to 7-bit levels. Bend maps -1 to 0, 0 to 8192,
and +1 to 16383, scaling negative and positive halves by 8192 and 8191 respectively.
Round to the nearest integer, with half values upward. Keep exact Motion values
in snapshots; the destination encoding alone quantizes them.

At each scheduled opportunity emit `step`, followed by `hit` if a source note
was admitted, otherwise `rest`. Ties emit only `step`. Repeated attacks from one
hit share one `hit` event. Gates and expression mappings already realized for
sounding notes or pending repeats remain unchanged by subsequent controls.

History and phrase banks emit `capture_ready` immediately before `step` when
publication changes a nonempty eligible bank. Its time, index, and revision
identify that publication boundary. Several captures published together produce
one notification. Committing alone does not notify; unfinished recording,
unchanged banks, and publication of an empty bank do not notify. Overdub,
replacement, and undo notify if they change the eligible bank to a nonempty one.
Readiness is independent of density or whether that step emits a note.

The output batch contains at most 4096 events. Reserve two event slots before
admitting a step, or three when it includes `capture_ready`, so the publication
notification, step, and outcome are admitted together. If full, skip new step
admissions and their notifications while keeping the published bank and owned
releases; draining the batch reports `exhausted = true` and permits subsequent
steps. No skipped attacks or notifications are replayed. Hosts drain after each
operation; the bank revision remains available in subsequent step events.

These ports do not execute a Motion graph. The host owns graph evaluation and
ordering, applies scalar samples before the target step, and routes output
events after collecting them. Feedback must arrive at a later opportunity with
an explicit delay of at least one scheduling quantum and a bounded event budget.
