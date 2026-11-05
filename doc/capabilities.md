# Implemented capabilities

This table describes Ufor's current reference implementation. Accepted definitions
can describe more than a particular preparer supports. Validation, pure reference
calculations, and host rendering are separate stages.

| Area | Definitions and validation | Implemented reference behavior | Host work or unsupported preparation |
| --- | --- | --- | --- |
| Scores, libraries and assets | Tagged score union, metadata, references, selectors, presets, local interfaces, structured file/volume/URL/Git/stream/Python locations | JSON/TOML interchange, schema generation, source/fact validation, explicit local library loading and normalization | Location policy, media acquisition/verification, provider execution, deployment and devices; schema alone is not full validation |
| Composition | Reference and signal graphs, ports, parameter configuration, exact clocks | Recursive resolution, interval propagation, event delivery, part-scoped numeric automation | Audio rendering, live inputs, tempo maps, speed changes; sample random/shuffle sets remain rejected by Composition even though standalone sample preparation supports them |
| Sample instruments | Assets/slices, inherited settings, mappings, selection, voice policies/pools, articulations, processing | Seeded cycle/random/shuffle selection, random ranges and variation; latched keyswitches, key/control conditions and control triggers; ordered starts/releases/sustain/chokes and part isolation | Momentary/control-driven articulations and mixed fade/envelope-release choke rules are rejected; audio exhaustion, DSP, sample traversal and final parameter realization require the definition and a host |
| Synth instruments | Oscillator, graph-FM, white-noise and Yamaha patch templates, mappings, settings and lifecycle declarations | Ordered voice starts/releases/sustain/chokes, voice limits, serialized source settings and deterministic random keys; composition performance delivery | Articulation preparation and public synth parameter exports are unsupported; waveform buffers and DSP belong to hosts |
| Pitch and scalar controls | Tunings, scales, shapes, Envelfo definitions/state, tempo maps, modulation, timeline automation | Exact arithmetic where possible, curve/shape evaluation, interruptible source smoothing, prepared trigger contexts, pitch composition, route and binding conversion, synth command quantization with a supplied tempo map | Stateful Envelfo execution belongs to enveLFO; audio-rate realization, antialiasing and scheduling belong to hosts |
| Audio effects | Acyclic graphs, gain, soft clip, filters, multiplication, bounded delays and granulators; action batches and capacities | Graph/layout/action validation, canonical processing order and scalar grain mathematics | enge owns DSP, transport admission, latency compensation and runtime snapshots; no effect score kind or automatic instrument attachment |
| Arpeggiators | Presets, capture/occurrence records, exact rhythm and control-port payloads | Preset/reference/domain validation and portable data interchange | arpeg owns selection engines, MIDI playback, capture publication, transport and runtime snapshots |
| Yamaha patch bytes | VL70, DX7, TX81Z and WT11 message/voice records; WT11 packed banks | Lossless parsing, diagnostics, supported relocation, decoded operator views, DX7 algorithm data and explicit WT11 instrument templates | Device transfer, requests and audible hardware equivalence |
| Event sequences | MIDI, UMP, OSC, keys and native performance events | Crop/seek/loop ownership planning and stored-event interchange | Device I/O and raw-MIDI-to-musical-trigger policy; TOML cannot encode OSC null array arguments, so use JSON |
| Light animation | Layouts, arbitrary components, effects, composition and wiring | Pure geometry/color calculations and composition checks | lyte owns frame production and device integration; physical output requires deployment validation |
| Fixture control | Parameter domains, byte encodings, cues, raw captures and patch metadata | Domain checks, physical footprint/collision checks | Sending DMX/Art-Net, synchronization and physical device validation |
| Slideshow and broadcast | Images/video, captions, transitions, accompaniment, sections, cue rules and run records | Selection filtering, local validation and transitive provisional broadcast timing | Decoding, display, audio playback, live cue delivery and capture |

Sample and synth traces are tied to the original definition. They are not
self-contained rendering plans. Instrument snapshots describe logical state,
not audio completion or resumable checkpoints; seeking currently replays the
ordered history from its beginning. See [sample performance](sample-performance.md)
for the action contract and the distinction from future player behavior.

The historical `format = "recs"` marker remains part of the wire format. Ufor is
the producer/library name. Python API naming changes do not imply a different
wire-format producer or an implemented audio engine.
