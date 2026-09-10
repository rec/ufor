# Composition example: rehearsal, drums and piano

This version-3 example is accepted by the codec and resolved in the test suite.
Its complete [score package](../conformance/composition/concert.toml) includes
all five scores. Asset metadata is synthetic; media and a sampler are not
included. See the [design](composition-design.md) and
[implementation plan](composition-implementation.md).

| Score | Public interface |
| --- | --- |
| Rehearsal recording | `desk`: stereo audio, at least ten seconds |
| Drums arrangement | `main`: stereo audio, at least ten seconds |
| Piano sequence | `performance`: native trigger/release/control events |
| Piano instrument | `performance` input; `audio` stereo output; `level_db` parameter |

All audio uses ordered channels `left`, `right` at 48,000 frames per second.
The sequence uses 48,000 ticks per second and supplies explicit target frequencies
for pitch-tracked samples. `level_db` is explicitly exported by the piano and
bound to its processing volume; its name does not confer any special behavior.

The parent refers directly to each definition, connects notes to the piano and
sums three audio clips. Its public output declaration contains its track binding
and range. The drums arrangement's internal structure remains private.

```toml
format = "recs"
version = 3
kind = "arrangement"
name = "concert"
title = "Rehearsal with drums and piano"
timebases = [{ name = "audio", rate = { numerator = 48000 } }]

[[outputs]]
name = "main"
binding = { track = "mix", start = 0, end = 480000, gain = 1.0 }
stream = { family = "sampled", quantity = "audio_amplitude", unit = "full_scale", timebase = "audio", channels = ["left", "right"] }

[body]
timebase = "audio"

[[body.parts]]
name = "rehearsal"
score = { path = "recordings/rehearsal.toml" }

[[body.parts]]
name = "drums"
score = { path = "mixes/drums.toml" }

[[body.parts]]
name = "notes"
score = { path = "sequences/piano.toml" }

[[body.parts]]
name = "piano"
score = { path = "instruments/piano.toml" }
parameters = { level_db = -6.0 }

[[body.connections]]
source = { name = "notes", output = "performance" }
destination = { name = "piano", input = "performance" }

[[body.tracks]]
name = "mix"
stream = { timebase = "audio", channels = ["left", "right"] }

[[body.clips]]
name = "rehearsal"
source = { name = "rehearsal", output = "desk" }
track = "mix"
source_start = 0
source_end = 480000
timeline_start = 0

[[body.clips]]
name = "drums"
source = { name = "drums", output = "main" }
track = "mix"
source_start = 0
source_end = 480000
timeline_start = 0

[[body.clips]]
name = "piano"
source = { name = "piano", output = "audio" }
track = "mix"
source_start = 0
source_end = 480000
timeline_start = 0

[[destinations]]
output = "main"
path = "renders/concert.wav"
format = "wav"
```

An offline request selects `main` over `[0, 480000)`, ten seconds. This example
cuts at that boundary. To retain a piano release through second twelve, extend
its clip, the public output binding and the request to frame 576000. The two
recorded contributions may keep their ten-second clips; outside those clips they
contribute silence, so no extra recorded frames are requested. The note sequence
need not be extended: its end generates no events and does not stop active voices.

Reading the same piano instance twice reads the same performance history. Adding
a second part with the same `definition.path` creates an independent performance,
with its own inputs, settings and state. File paths may repeat; there is no
separate dependency-ID namespace.

The model can be validated before an instrument engine exists. A host lacking a
piano implementation must report it as unsupported rather than omit its audio.
Nested recording-only arrangements use Recs' existing renderer.
