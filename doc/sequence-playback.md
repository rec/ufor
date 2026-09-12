# Sequence selection and playback

`ufor.playback.plan_playback(sequence, selection)` is a pure planner. It selects
an integer, half-open interval in the sequence's native timebase, moves its start
to `selection.start`, and repeats it `selection.repetitions` times. The source
sequence remains unchanged. No audio, network packets, or operating-system key
events are generated.

A `SequenceSelection` has a unique clip `name`, an `interval` (`start`, `end`),
a destination `start` (default zero), a positive `repetitions` (default one), and
`active_notes`: `retrigger_active` (default) or `omit_active`.

## Seeking and looping

`state_at(sequence, tick)` reconstructs semantic state strictly before the tick.
It returns active triggers and the most recent change for each scoped control.
Trigger controls disappear on release. Initial values carried by a trigger remain
in its `controls`; subsequent changes are in the state's control list. Unknown
control values are not guessed. A release or trigger control must address an
active trigger; another trigger cannot reuse an ID while it is active in its
part. Reuse after release is allowed, and separate parts may use the same ID.
Raw protocol events do not participate in this validation or reconstruction.

Each returned `PlaybackIteration` contains native `timebase`, `start`, `end`,
`name`, iteration number, and four ordered lists:

1. `controls`: the complete instrument/part control snapshot at the selection
   start. The host restores declared defaults for this clip's control context,
   then applies this snapshot. It must not reset unrelated clips' controls.
2. `events`: executable semantic triggers, releases, and control changes.
   Retriggered notes precede their restored trigger controls and selected events.
   Retriggering restarts envelopes; it does not reconstruct an audio voice.
3. `captured`: inert raw MIDI, UMP, OSC, or key events within the selection.
   Their payloads and source ordinals are preserved, with ticks moved to the
   destination timeline. Keep the source sequence for original timestamps.
   These records are not another dispatch list.
4. `cleanup`: releases at the exclusive end for every still-owned trigger.
   Apply these before the next iteration's snapshot and events, even when their
   timestamps match. Cleanup is separate because end events are outside the
   authored sequence's half-open extent.

With `omit_active`, notes begun before the selection, their trigger controls,
and their later releases are omitted. Newly triggered notes still play normally.
Events exactly at the end are excluded. An empty selection is rejected; a
nonempty interval containing no events produces silence of the requested length.

Owned trigger IDs are `clip-{length of name}-{name}-{iteration}-{original ID}`.
Iterations start at zero. The length prefix prevents ambiguous clip names from
colliding. Concurrent selections must have different names. Generated semantic
ordinals follow playback order; capture ordinals retain their source identities.

A host interrupting an iteration must release its currently active owned triggers
before replacing it with a newly planned seek. The planner supplies end cleanup;
it does not track a running host. Sustain and actual voice retirement belong to
the MIDI adapter and instrument. This contract prevents unmatched semantic notes,
not hardware faults or an instrument ignoring releases.

## Universal MIDI Packets

`UmpEvent` has the ordinary `tick`, `ordinal`, and `kind = "ump"`, plus `words`:
one to four exact unsigned 32-bit integers, in packet order. Packet length is
validated against the message-type nibble, including lengths of reserved types.
Unknown words and statuses are preserved. Numeric words avoid a file byte-order
convention; transport adapters are responsible for their own byte order.

Read-only properties expose `message_type`, zero-based wire `group` for known
grouped message types (otherwise null), and `sysex_format` (`sysex7`, `sysex8`, or
null). MIDI 1.0 channel voice is type 2 and MIDI 2.0 channel voice is type 4.
Type 3 SysEx statuses 0 through 3 identify SysEx7; type 5 statuses 0 through 3
identify SysEx8. Other type 5 messages are not labeled SysEx8. This layer does
not validate every protocol field, reassemble SysEx, interpret notes, or perform
lossy MIDI 2.0 to MIDI 1.0 conversion.

Sequences and native `recs_events` recording streams accept `ump`. There is no
new MIDI byte-stream encoding. MIDI-CI discovery, Profiles, Property Exchange,
request execution, and device dispatch remain host work for later milestones.

Packet sizes follow [USB MIDI 2.0, table 3-1](https://www.usb.org/sites/default/files/USB%20MIDI%20v2_0.pdf).
The [Universal MIDI Packet specification](https://midi.org/universal-midi-packet-ump-and-midi-2-0-protocol-specification)
defines the protocol families. `conformance/ump.json` supplies portable examples,
including reserved content; `conformance/sequence-playback.json` demonstrates
loop ownership and cleanup.
