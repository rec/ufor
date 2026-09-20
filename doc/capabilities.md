# Implemented capabilities

This table describes Ufor's current reference implementation. Accepted definitions
can describe more than a particular preparer supports. Validation, pure reference
calculations, and host rendering are separate stages.

| Area | Definitions and validation | Implemented reference behavior | Host work or unsupported preparation |
| --- | --- | --- | --- |
| Scores, libraries and assets | Tagged score union, metadata, references, selectors, presets, local interfaces, structured file/volume/URL/Git/stream/Python locations | JSON/TOML interchange, schema generation, source/fact validation, explicit local library loading and normalization | Location policy, media acquisition/verification, provider execution, deployment and devices; schema alone is not full validation |
| Composition | Reference and signal graphs, ports, parameter configuration, exact clocks | Recursive resolution, interval propagation, event delivery, part-scoped numeric automation | Audio rendering, live inputs, tempo maps, speed changes; sample random/shuffle sets remain rejected by Composition even though standalone sample preparation supports them |
| Sample instruments | Assets/slices, inherited settings, mappings, selection, voice policies, articulations, processing | Seeded cycle/random/shuffle selection, random ranges and variation; ordered starts/releases/sustain/chokes, voice limits and part isolation | Articulation preparation is rejected; mixed fade/envelope-release choke rules are rejected; audio exhaustion, DSP, sample traversal and final parameter realization require the definition and a host |
| Synth instruments | Oscillator templates, mappings, settings and lifecycle declarations | Ordered voice starts/releases/sustain/chokes, voice limits, full serialized synth settings; composition performance delivery | Articulation preparation and public synth parameter exports are unsupported; waveform buffers and DSP belong to hosts |
| Pitch and scalar controls | Tunings, scales, shapes, envelopes, LFOs, modulation, timeline automation | Exact arithmetic where possible, scalar evaluation, envelope/LFO event state, interruptible source smoothing, prepared trigger contexts, pitch composition, route and binding conversion | Audio-rate realization, antialiasing and host scheduling |
| Event sequences | MIDI, UMP, OSC, keys and native performance events | Crop/seek/loop ownership planning and stored-event interchange | Device I/O and raw-MIDI-to-musical-trigger policy; TOML cannot encode OSC null array arguments, so use JSON |
| Light animation | Layouts, arbitrary components, effects, composition and wiring | Pure geometry/color calculations and composition checks | Frame production, device output and Lyte integration |
| Fixture control | Parameter domains, byte encodings, cues, raw captures and patch metadata | Domain checks, physical footprint/collision checks | Sending DMX/Art-Net, synchronization and physical device validation |
| Slideshow and broadcast | Images/video, captions, transitions, accompaniment, sections, cue rules and run records | Selection filtering, local validation and transitive provisional broadcast timing | Decoding, display, audio playback, live cue delivery and capture |
| SFZ | Source metadata and supported opcode conversion | Pure compile/export with explicit unsupported-feature reports | File discovery, sample inspection and audio rendering |

Sample and synth traces are tied to the original definition. They are not
self-contained rendering plans. Instrument snapshots describe logical state,
not audio completion or resumable checkpoints; seeking currently replays the
ordered history from its beginning. See [sample performance](sample-performance.md)
for the action contract and the distinction from future player behavior.

The historical `format = "recs"` marker remains part of the wire format. Ufor is
the producer/library name. Python API naming changes do not imply a different
wire-format producer or an implemented audio engine.
