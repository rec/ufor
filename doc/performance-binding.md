# Performance input bindings

A `performance_binding` score describes how a protocol input becomes native
`Trigger`, `Release`, and `ControlChange` events for one referenced instrument.
It is separate from the host-adapter `binding` score: it contains no device
address, host implementation, or executable transport. The first source profile
is MIDI 1 channel voice messages. Other protocols require their own explicit
source profile rather than being interpreted as MIDI fields.

`body.instrument` is a score reference to the target instrument. Each entry in
`body.midi` maps one or more one-based MIDI channels to a native part. Channel
sets may not overlap. `repeated_key_release` is required because MIDI note-off
messages carry a key and channel but no identity for overlapping note-ons of
the same key. `oldest` releases the earliest still-held onset; `newest` releases
the most recent. Pairing state is separate for each channel and key. A host
allocates a fresh native trigger ID for each note-on and retains it through its
matching release.

MIDI note-on with velocity 1 through 127 becomes `Trigger` with the MIDI key and
velocity divided by 127. Note-on with velocity zero is a note-off. Native
`pitch_hz` follows the referenced tuning, or 12-tone equal temperament with
A4 = 440 Hz when `tuning` is absent. The host preserves exact input event ticks
and ordinals or converts them to the instrument input timebase without floating
point drift. This document does not create a second event clock.

Each `controllers` entry maps a MIDI CC number to a declared named instrument
control. For incoming value `v` from 0 through 127, its part-scoped
`ControlChange` value is `minimum + (maximum - minimum) * v / 127`. The output
range must increase and stay within the native bipolar domain; the referenced
instrument must declare the control and accept that range. Unmapped CC numbers
have no effect. Sustain has no implicit CC number: mapping CC 64 to `sustain`
must be explicit. Initial control values come from the instrument declaration
until a mapped message arrives.

Optional `pitch_bend` maps signed MIDI bend `b` (−8192 through +8191) to a
declared named control. Its `control`, `minimum`, `center` and `maximum` fields
describe an increasing piecewise-linear mapping, with default values −1, 0 and
+1. Require `minimum < center < maximum`, all in the native bipolar domain,
and validate that the instrument's control accepts the whole range. For `b < 0`,
the value is `center + (center - minimum) * b / 8192`; otherwise it is
`center + (maximum - center) * b / 8191`. Thus −8192, zero and +8191 reach the
three declared values exactly. The result is a part-scoped `ControlChange`,
not an implicit alteration of `Trigger.pitch_hz`. Without `pitch_bend`, bend
has no effect. There is no assumed bend name or semitone range.

The score defines conversion semantics, not a live MIDI adapter. A host must
still open the input, track note identities, resolve the referenced instrument
and tuning, validate declared controls, and emit native performance events.
The [portable example](../conformance/performance-binding.json) records one
explicit repeated-key rule, a sustain-pedal mapping and an explicit bend target.

safaz can produce this binding score during SFZ import. Its conversion
contract and source-specific diagnostics live in the
[safaz documentation](https://github.com/rec/safaz/blob/main/doc/conversion.md).
