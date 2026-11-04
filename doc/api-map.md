# API and ownership map

Import symbols from their defining modules. Names below are canonical; there are
no compatibility aliases for the earlier API. The serialized score kind
`instrument` and format marker `recs` remain unchanged. `recs` identifies the
historical wire format, not the producer. safaz owns SFZ conversion.

| Task | Defining modules and entry points |
| --- | --- |
| Read, write, migrate, or describe a score | `codec.parse_score`, `score_toml`, `migrate_score_v3`, `score_schema`; `score_types.ScoreValue` lists the supported kinds |
| Describe asset acquisition | `assets.Asset`, `ContentIdentity`, and the six location models; `PythonProviderLocation.delivery` distinguishes complete buffers, borrowed callbacks, and client-owned pull buffers |
| Reference and connect scores | `interface.ScoreReference`, `Part`, `InputSelection`, `OutputSelection`; port selections use `part` and `input` or `output` |
| Resolve compositions | `composition.Composition`; `library` resolves selectors and presets; `library_files` supplies explicit local file access |
| Select library records | `selector` defines literal selectors; `references.RecordSelector` selects recording streams, not score definitions |
| Arrange audio and controls | `arrangement.Track`, `Bus`, `Clip`, `BusRoute`, `ControlClip` |
| Store or plan events | `sequence.EventSequence`, `events`; `playback` plans event cropping, seeking, and loops |
| Define sample instruments | `samples.instrument.SampleInstrumentScore`, `SampleInstrument`, `SampleSettings`; shared settings are at `body.settings` |
| Define synth instruments | `synth.SynthInstrumentScore`, `SynthInstrument`, `SynthVoice` |
| Define other synth sources | `synth.FMVoice`, `fm.FM`; `synth.NoiseVoice`, `noise.stream_key` |
| Preserve Yamaha synth templates | `synth.YamahaDX7Voice`, `YamahaTX81ZVoice`; raw patch models remain in `dx7` and `tx81z` |
| Declare shared TX81Z DAC ownership | `synth.TX81ZOutput`, `SynthInstrument.tx81z_outputs`; explicit template membership and post-DAC processing/routes |
| Define reusable generators | `envelfo.EnvelfoScore`, `LFO`, `Envelope`, `Stages`, `SampleHold`, `Patch`; stateful execution belongs to enveLFO |
| Describe audio effect graphs | `audio_effects.EffectGraph`, `ActionBatch`, `validate_action`, `validate_batch`; execution belongs to enge |
| Describe arpeggiation | `arpeggiator.ArpeggiatorScore`; `arpeggiator_capture` owns captured phrases/occurrences; `arpeggiator_ports` owns controls and notifications |
| Read Yamaha patch bytes | `vl70.parse_vl70`, `dx7.parse_dx7`, `tx81z.parse_tx81z`; no device I/O |
| Inspect TX81Z performance allocations | `tx81z.TX81ZEntry.performance`, `TX81ZPerformance.instruments`; lossless PCED bytes and decoded allocation/LFO selectors |
| Prepare instrument lifecycles | `samples.trace.prepare` returns `SampleTrace`; `synth_trace.prepare` returns `SynthTrace`; `instrument_trace` owns common actions and `LifecycleSnapshot` |
| Evolve instrument controls | `samples.controls.initial_control`, `control_event`, `control_at`; `instrument_trace.TriggerContext` preserves onset initialization |
| Realize scalar instrument pitch | `synth.frequency` consumes prepared Hz and final routed cents; `samples.playback.pitch_ratio` combines tracked pitch, tuning, and resolved variation |
| Work with pitch | `tuning`, `scale`, `scala`, `oscillator`; `number.PitchNumber`, `cents_to_ratio`, `ratio_to_cents` preserve explicit arithmetic intent |
| Declare finite scalar fields | `base.FiniteScalar`; `base.NoteKey` is a strict integer musical selection key, independent of rendered pitch |
| Describe lights | `lights` owns layouts/contracts, `light_animation` composes effects, `effects` contains light effect definitions, `light_math` evaluates geometry/color scalars |
| Bind an adapter | `binding.StreamContract` summarizes capabilities; `StreamMapping.stream` selects a declared stream and `native` names its adapter endpoint; bindings store these in `stream_mappings` |

`modulation.Target.name` identifies an owner in the containing model's namespace.
For exported arrangement parameters it names a child part; inside a processor it
can instead name `processing`, an EQ/filter, `animation`, or `renderer`. It is
therefore intentionally distinct from the `part` field on port selections.

`Computed.denominator_limit` bounds rational approximation. `Tuning.detune_cents`
is a pitch offset. `Oscillator.key_scale_db_per_12_steps` specifies gain change per
twelve note-number steps, even when the tuning's period is not twelve steps.
`RatioTable.name` and `.description` preserve the source tuning-table metadata,
such as a Scala scale's name and description; the containing score's name/title
identify its library record. These are separate ownership levels.

## Shared instrument concepts

The `samples` namespace reflects extraction history. The following definitions
are shared by sample and synth instruments today, and are not sample-only APIs:

| Shared concept | Current owner | Consumers |
| --- | --- | --- |
| Controller value domain | `samples.controls.ControlDeclaration` | Sample/synth declarations; distinct from `light_animation.Control`, which defines a named generator |
| Key, velocity, and pitch mapping | `samples.playback.Mapping` | Sample slots and synth voices |
| Sound processing and channel routes | `samples.processing` | Both instrument kinds |
| Trigger and retirement policies | `samples.enums`, `samples.selection` | Both instrument preparers |
| Voice/trigger identity and retirement actions | `instrument_trace` | Both preparers |

`samples.playback.Slice`, source-frame traversal, loop points, and sample `Playback` remain
sample-specific. `samples.enums.CrossfadeInput` selects a key, velocity, or
controller value; `interface.Input` is a public stream port.

Shared definitions do not imply identical preparation: samples select assets,
apply seeded selection and variation, and distinguish one-shot playback; synths
select source templates and preserve oscillator, FM, noise, or Yamaha settings. Shared lifecycle
conformance cases run against both preparers. Keep these behavioral checks when
changing either implementation. A single configurable preparer is not required
by the format, and module moves should follow a concrete ownership need rather
than the current filenames alone.

See [capabilities](capabilities.md) for implemented behavior and limits, and
[control choices](control-guide.md) for overlapping control concepts.

Ufor owns asset declarations and validation only. A host maps volumes, downloads
and verifies finite URLs, resolves pinned Git blobs, opens streams, and imports
trusted Python providers. Callback providers lend read-only arrays until the
callback returns; client-buffer providers fill writable arrays owned by the
consumer. Neither protocol is implemented by Ufor core, and NumPy is not a Ufor
dependency.
