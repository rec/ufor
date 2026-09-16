# Ufor review issues

Reviewed 2026-09-16 against `9b64f67`.

This is a static review of the public models, codecs, library resolution,
composition, instrument preparation, scalar calculations, format documentation,
and relevant tests/conformance cases. No application, library execution, or test
suite was run. “Confirmed” below means the behavior follows from the inspected
code; the examples are proposed regression cases, not executed reproductions.
“Design concern” identifies a contract or API decision rather than a demonstrated
runtime failure. This is a backlog, not authorization to implement the suggestions.

Priority: P1 means silent semantic changes or incorrect preparation; P2 means
validation, interoperability, or usability problems; P3 means naming and
maintenance concerns. Resolve correctness before undertaking naming changes.

## Correctness and semantic preservation

### 1. Slot-group inheritance does not survive normalization and serialization

**Resolved:** omitted categories and explicit processing overrides survive
JSON, TOML, library normalization, and presets. `selection = false` disables
selection; omitted/null selection inherits. Explicit null envelope overrides use
`envelope = false` in TOML. Regression tests cover neutral and disabled overrides.

**P1, confirmed.** [instrument.py:159](../ufor/samples/instrument.py#L159)
and [codec.py:69](../ufor/codec.py#L69).

`effective_settings` and `effective_selection` use `model_fields_set` to tell
omission from an explicit override. `score_toml` dumps all defaults and validates
that dump again. `Library.normalize_references` likewise visits every field,
including defaults. A slot that inherits a group's `volume_db = -6` therefore
acquires an explicit default processing category and stops inheriting. A library
normalization also turns an omitted selection into an explicit `None`.

There is a second ambiguity: TOML serialization drops `None`, so an explicit
`selection=None` override cannot remain distinguishable from omission. The
existing group test checks the live objects, not these interchange boundaries.
Specify a portable omission/override representation and test effective behavior
through TOML, JSON, library loading, and presets, including explicit neutral values.

### 2. Random selection always uses the same draw for a state partition

**Resolved:** random draws use the persisted advancing counter. Regression
coverage checks progression and reproducible replay of the same state partition.

**P1, confirmed.** [selection.py:115](../ufor/samples/selection.py#L115).

The random branch increments `sequence.counter` but calls `_index(..., 0)`.
`_index` hashes its explicit counter argument, not `sequence.counter`. Repeated
choices with the same seed, part, trigger kind, key, and candidate list therefore
select the same candidate forever. Use the advancing state in the draw and add
a portable multi-draw case. Determinism alone does not test random progression.

### 3. Shuffle refill can immediately repeat the preceding choice

**Resolved:** refills protect the first nonrepeating choice and shuffle only
the remaining positions. Regression coverage checks 32 seeds.

**P1, confirmed.** [selection.py:159](../ufor/samples/selection.py#L159),
[sample-performance.md:91](../doc/sample-performance.md#L91).

The refill puts a candidate other than the previous choice at index zero, then
shuffles the entire list, including index zero. The supposedly protected first
choice can be replaced by the preceding choice. This contradicts the documented
algorithm, which shuffles only the remaining positions. Cover refill boundaries
over multiple seeds, not just uniqueness within each bag.

### 4. Chokes ignore both mode and part ownership

**Resolved:** both preparers isolate chokes by part and preserve stop, release,
and fade semantics. Fade retirement carries its duration; unsupported combined
fade/envelope-release rules fail explicitly. Shared tests cover all three modes.

**P1, confirmed.** [sample trace:156](../ufor/samples/trace.py#L156),
[synth trace:114](../ufor/synth_trace.py#L114),
[choke contract](../doc/sample-performance.md#L145).

Both preparers search all voices for a matching group and always emit `stop`.
A choke on one part can terminate another part's voices; `release` and `fade`
are silently treated as immediate stops. `fade_seconds` has no representation
in `VoiceRetirement`. Implement the declared subset faithfully or reject the
unsupported modes before preparation. Cases must distinguish parts and all
three choke modes.

### 5. Same-key policy retires layers started by the same trigger

**Resolved:** policy retirement happens before the new batch starts. Capacity
is reserved for the whole batch; a batch exceeding the limit is rejected, as
requested. Shared regression cases cover layered replacement and oversized batches.

**P1, confirmed.** [sample trace:160](../ufor/samples/trace.py#L160),
[synth trace:118](../ufor/synth_trace.py#L118).

Same-key retirement runs separately for each selected slot/template. With two
layers and `same_key=release` or `replace`, the second layer sees and retires the
first layer just started for this same onset. Compare against previously active
onsets before creating the batch. The related maximum-voice behavior also needs
an explicit decision when one onset creates more layers than the limit.

### 6. Release voices lose the original pitch

**Resolved:** physical and sustain-deferred logical releases retain their
owning trigger's pitch, including synth offsets. Both preparers have regression cases.

**P1, confirmed.** [sample trace:209](../ufor/samples/trace.py#L209),
[synth trace:155](../ufor/synth_trace.py#L155).

`ActiveTrigger` retains `pitch_hz`, but voice creation reads pitch only from a
current `Trigger` event. Physical-release voices are created from `Release` and
deferred logical-release voices from `ControlChange`, so both receive `None`.
The documented release contract explicitly preserves the original target pitch.
Pass the owning trigger's pitch through both release paths, including the synth
frequency offset, and cover sustain-deferred release.

### 7. One-shot sample voices are released like while-held voices

**Resolved:** ordinary logical release retires only while-held sample voices;
one-shots retain their active voice and their trigger records logical release.

**P1, confirmed.** [sample trace:371](../ufor/samples/trace.py#L371),
[playback models](../ufor/samples/playback.py#L54).

The logical-release path retires every active start voice with action `release`.
It never resolves the slot/instrument playback mode. A start slot with
`mode=one_shot` consequently receives the same retirement as `while_held`, despite
the contract that ordinary release must not truncate one-shots. Carry enough
resolved lifecycle information to distinguish them or explicitly constrain the
preparer's supported profile.

### 8. Accepted articulation declarations are silently ignored by preparers

**Resolved:** sample and synth preparation explicitly reject articulation
declarations until their execution semantics are implemented.

**P1, confirmed implementation gap.** [sample trace:85](../ufor/samples/trace.py#L85),
[synth trace:69](../ufor/synth_trace.py#L69).

Eligibility filters do not inspect articulations, keyswitches, control switches,
or consumed triggers. Slots/voices for incompatible articulations can start
together, and a consumed switch can produce sound. Documentation defers parts of
articulation execution, but the preparers accept these definitions without a
diagnostic. Reject unsupported declarations until their semantics are implemented;
do not present the resulting trace as fully resolved.

### 9. Prepared voice payloads are not the complete rendering contract advertised

**Resolved by the approved boundary:** traces require the original definition;
documentation lists unresolved responsibilities. Synth actions serialize the full
SynthVoice settings, with a regression test for hold time and synchronization.

**P1, confirmed gap; contract decision needed.**
[sample VoiceStart](../ufor/samples/trace.py#L34),
[synth VoiceStart](../ufor/synth_trace.py#L27),
[trace documentation](../doc/sample-performance.md#L19).

Sample preparation supplies slot/group `SoundSettings` but not the separate
instrument sound-settings contribution; `parameters` is left empty. The action
does not resolve playback direction/mode, loop policy, or crossfade behavior.
Synth actions type `settings` as `SoundSettings` while passing a `SynthVoice`:
subclass-only fields such as `minimum_hold_seconds` and
`synchronize_oscillator` are not declared in that serialized payload.

A consumer needs the original definitions and additional policy, contrary to the
claim that it need not repeat format decisions. Specify which definition lookup
is part of the engine interface and which settings preparation guarantees. Test
the serialized trace, not only access to the in-memory subclass object.

### 10. Snapshots cannot restore the documented semantic state

**Resolved by the approved boundary:** snapshots are explicitly observational;
seeking requires full replay. No resumable-snapshot API is claimed or introduced.

**P1, confirmed gap.** [snapshot schema](../ufor/instrument_trace.py#L79),
[sample preparation](../ufor/samples/trace.py#L71).

The preparer's per-part sustain state is local and absent from snapshots.
Current addressed control values and articulation state are also absent. A held
trigger alone cannot reveal whether the pedal is currently pressed. There is
no preparation entry point accepting a prior snapshot. The documentation promises
seeking by restoring one and replaying later events. Either define a complete
resumable semantic snapshot or narrow that promise to observation-only output.

### 11. Voice IDs have delimiter collisions and no onset generation

**Resolved:** trace-local sequential voice IDs cannot collide through component
spelling. Active trigger reuse is rejected; released IDs without owned logical
voices may be reused and subsequent releases address the new onset.

**P1, confirmed.** [sample trace:181](../ufor/samples/trace.py#L181),
[synth trace:139](../ufor/synth_trace.py#L139).

IDs concatenate part, trigger ID, and template using hyphens, but hyphens are
legal inside every component. `(part='a-b', trigger_id='c')` and
`(part='a', trigger_id='b-c')` produce the same ID for the same template.
The global uniqueness check then rejects otherwise distinct voices. Reusing an
onset ID after its lifetime also reuses the voice ID; triggers remain in a list
and release lookup takes the first match. Define unambiguous identity encoding
and its lifetime. Include distinct-part collisions and eventual reuse in cases.

### 12. ControlChange validation is skipped during preparation

**Resolved:** both preparers validate every event against declared control domains.

**P2, confirmed.** [sample trace:261](../ufor/samples/trace.py#L261),
[synth trace:204](../ufor/synth_trace.py#L204).

Both instrument models provide `validate_event` for triggers and control changes,
but preparation invokes it only for triggers. An undeclared control, or a
negative value for a declared unipolar control, becomes a trace observation.
Apply the instrument's event contract consistently before changing state.

### 13. Snapshot coordinates can precede the actions they describe

**Resolved:** both preparers use one sorted event list for processing and snapshot
coordinates, and reject duplicate event coordinates. Shared tests cover both cases.

**P2, confirmed.** [sample trace:412](../ufor/samples/trace.py#L412),
[synth trace:340](../ufor/synth_trace.py#L340).

Preparation sorts its input events, but stamps the final snapshot with
`events[-1]` from the original unsorted list. Input ordered as ticks `[10, 0]`
produces final state through tick 10 labeled tick 0. Either require ordered
input or consistently use the processed ordering. Also define how duplicate
event coordinates are handled for this list-based API.

### 14. Synth instruments cannot use the composition performance path

**P2, confirmed integration gap.**
[composition.py:273](../ufor/composition.py#L273),
[composition.py:460](../ufor/composition.py#L460).

The codec and interface accept `SynthInstrumentScore`, but performance traversal
only recognizes sample `InstrumentScore`. An event connection to a synth can
fail with “no performance consumer”; a trace traversal skips synth parts.
Configurable parameter resolution likewise lacks a synth branch. Make the
supported composition profile explicit and either support the sibling contract
or reject it at a clear boundary rather than after apparently compatible wiring.

### 15. Group-inherited spatial processing bypasses channel-layout validation

**P1, confirmed.** [instrument.py:408](../ufor/samples/instrument.py#L408).

Instrument validation computes effective group/slot settings earlier, but the
score's pan/stereo-balance layout check examines only `self.body.instrument`
and the raw slot. Put nonzero pan solely in a group and this check sees no active
pan. An incompatible source layout or noncanonical channel map can pass.
Validate spatial processing against the same resolved categories used by preparation.

### 16. SFZ export can silently omit newly supported native features

**P1, confirmed.** [sfz.py:237](../ufor/sfz.py#L237),
[sfz.py:325](../ufor/sfz.py#L325), [sfz.py:903](../ufor/sfz.py#L903).

The writer reads raw slots, never resolves slot groups, and does not diagnose
group-inherited processing, `voice_policy`, or variation declarations. It can
therefore return `complete=True` while exporting materially different behavior
from a document with those settings. Audit the exporter field by field: either
translate effective semantics or emit a precise unsupported-feature diagnostic.
Use an otherwise representable instrument with one nondefault feature per case.

### 17. Tuning evaluation discards exact fractions even with no detuning

**P2, confirmed.** [tuning.py:103](../ufor/tuning.py#L103),
[number.py:12](../ufor/number.py#L12).

`Tuning.__call__` always multiplies by the floating-point result of `cents`.
Even a rational source and root frequency with `detune=0` becomes a float.
`Computed` also uses floating division for its exponent even for integral
period offsets. Preserve exact arithmetic where the mathematical operation
is exact, and document where approximation becomes intentional. Test types and
exact values as well as approximate frequency equality.

### 18. OSC null arguments have no declared TOML representation

**P2, interoperability risk.** [events.py:70](../ufor/events.py#L70),
[codec.py:70](../ufor/codec.py#L70).

`OscMessage.args` permits `None` within a list. The serializer excludes `None`
model fields, but that does not supply an encoding for a positional null argument
in TOML, which has no null value. Specify how this valid model is represented or
rejected at interchange, without dropping or shifting arguments. Add a codec
case for a decoded OSC message containing a null argument.

## Validation, ownership, and data-shape traps

### 19. “Frozen” and “immutable” have conflicting meanings across the API

**P2, design concern grounded in current behavior.**
[base.py:9](../ufor/base.py#L9),
[musical editing contract](../doc/musical-format.md#L143).

Frozen models prevent field replacement, not list/dict mutation. The musical
documentation deliberately permits collection editing; composition and instrument
documentation call definitions immutable. A validated sequence's event list can
be reordered or a score's channel list changed without rerunning its validators.
Reference functions generally trust these invariants. Clarify the validation
boundary for every public consumer and distinguish editable definitions from
validated snapshots. Do not blindly replace collections: editable lists are an
explicit current design choice.

### 20. Composition mutates and retains the caller's score registry

**P2, confirmed ownership trap.** [composition.py:81](../ufor/composition.py#L81),
[composition.py:536](../ufor/composition.py#L536).

`self.scores = scores` aliases the caller's dictionary; resolving inline scores
adds synthetic entries to it. `Library.composition` passes `self.records`
directly. Merely preparing a composition can thus modify library state, even
before a later validation failure. Subsequent compositions inherit those entries.
Define ownership and isolate resolution additions from the input registry.

### 21. Instrument tags violate the common score/library tag contract

**P2, confirmed.** [score.py:16](../ufor/score.py#L16),
[sample score:359](../ufor/samples/instrument.py#L359),
[synth score:137](../ufor/synth.py#L137), [Entry](../ufor/library.py#L41).

Most scores require `Tags`, which validates `#` prefixes and deduplicates.
Sample and synth scores replace it with `list[Text]` and reject duplicates.
Consequently a codec-valid instrument tagged `piano` can be rejected by the
library's metadata pass. Use one score-level tag contract; keep slot metadata
distinct if it intentionally has different semantics.

### 22. Scale interval input can be silently truncated despite the integer contract

**P2, confirmed.** [scale.py:20](../ufor/scale.py#L20).

The before-validator calls `int(c)` on every supplied element. Values such as
`1.9` or `True` become integer 1 before list validation sees them. The documented
contract says nonnegative integer intervals. Validate that conversion preserves
the authored value rather than silently changing the scale. Separately, unknown
note text and extra fields are intentionally permissive here; make that exception
obvious to callers accustomed to other models' `extra='forbid'` behavior.

### 23. Binding scopes and stream types form a second, incompatible vocabulary

**P2, design concern.** [binding.py:43](../ufor/binding.py#L43),
[binding.py:68](../ufor/binding.py#L68), [control.py:17](../ufor/control.py#L17).

`InputControl.scope` uses global/performance/voice; shared controls use
instrument/part/voice, and performance changes additionally use trigger.
`StreamContract.family='audio'` differs from `AudioType.family='sampled'` plus
`quantity='audio_amplitude'`. Binding channels are counts; public ports have
named channel layouts. No common mapping explains these differences.
Document explicit translations or use the common vocabulary where semantics
really are the same. Similar spelling must not imply compatibility.

### 24. Fixture validation does not establish a usable physical patch

**P2, confirmed gaps.** [fixture.py:94](../ufor/fixture.py#L94),
[fixture.py:217](../ufor/fixture.py#L217).

Channel encodings only check that the parameter name exists, not whether numeric
versus discrete encoding matches its domain or whether all choices are covered.
Slots may overlap across parameter encodings. `patch_fixtures` checks fixture
coverage and nonnegative wire universe, but not profile footprint: a fixture
starting at 512 with a second relative slot exceeds the universe, and two fixtures
can occupy the same slots. Define intentional aliasing if supported; otherwise
reject contradictory encodings and impossible/colliding placements.

### 25. Broadcast provisional timing is not propagated through dependencies

**P2, confirmed.** [broadcast.py:226](../ufor/broadcast.py#L226).

`provisional_sections` returns only sections directly using cue rules. A section
starting `after` a cue-driven section has an unknown absolute start too but is
reported as nonprovisional. Propagate provisional status through the existing
acyclic dependency graph, or rename/document the function as a direct cue filter.
Also reject `earliest`/`deadline` on non-cue starts: those fields currently pass
unchecked and have no specified meaning there.

### 26. Slideshow defaults, transitions, and caption language can conflict

**P2, confirmed gaps.** [slideshow.py:59](../ufor/slideshow.py#L59),
[slideshow.py:125](../ufor/slideshow.py#L125),
[slideshow.py:166](../ufor/slideshow.py#L166).

`default_advance` has no resolution logic, while every slide already defaults to
`automatic`; the authored distinction between inheritance and explicit automatic
is unspecified. Multiple transitions for the same adjacent pair are accepted,
and a cut can carry nonzero duration, unlike a broadcast cut. A caption track
declares one language but does not check embedded caption languages. Define
effective advancement and reject or specify these contradictory declarations.

### 27. Piecewise binding conversion has asymmetric endpoint behavior

**P2, confirmed; intended policy unclear.**
[binding.py:96](../ufor/binding.py#L96),
[binding.py:169](../ufor/binding.py#L169).

Piecewise points need not cover the declared input domain. Below the first point,
mapping extrapolates along the first segment; above the last, it holds the last
output. Neither the model nor the documentation makes that asymmetry explicit.
Require endpoint coverage or specify a consistent endpoint policy and test it.
Enum maps also require irrelevant numeric input/output bounds, making discrete
authoring unnecessarily awkward.

### 28. Score-model construction depends on a codec import side effect

**P2, API risk.** [interface.py:19](../ufor/interface.py#L19),
[interface.py:69](../ufor/interface.py#L69),
[codec.py:98](../ufor/codec.py#L98).

`Part` refers to a `ScoreValue` available only under `TYPE_CHECKING`; the codec
later rebuilds the model using its runtime union. Direct imports from the defining
module therefore do not establish the same initialization state as importing
the codec first. Verify direct construction in a fresh interpreter and remove
the hidden ordering requirement. Tests that import the codec early can mask it.

## Naming and API clarity

These are review candidates, not a request for blanket renaming. A standard-library
collision is not inherently a bug when the domain meaning is conventional.

| Priority | Name and location | Problem and suggested direction |
| --- | --- | --- |
| P2 | `ScoreVersion`, `interface.py:23` | Represents a reference by path or selector, optionally pinned by digest; contains no version. `ScoreReference` would describe the value more accurately. Keep wire-format version distinct. |
| P2 | `Instrument`, `SampleInstrument`, `InstrumentScore`, `samples/instrument.py` | The generic `Instrument` is only the shared settings inside a sample body; the fully assembled body is `SampleInstrument`. This produces `score.body.instrument` and `instrument.instrument`. Name the settings layer explicitly and make sample/synth score names symmetric. |
| P2 | `Number`, `base.py:37` versus `number.py:8` | One is a constrained float; the other includes integers and exact fractions. Both compete with the conventional `numbers.Number` concept. Prefer names expressing finite scalar versus exact-capable pitch arithmetic, or eliminate a needless alias. |
| P2 | `cents` / `uncents`, `number.py:12` | `cents` returns a ratio, not a cents value; `uncents` returns cents. `cents_to_ratio` and `ratio_to_cents` make direction and units explicit. |
| P2 | `name` in `InputSelection`, `OutputSelection`, `Target` | It names the owning part or local object, not the selection/target itself. Prefer `part` for port selections; document the target namespace separately because `animation`, `renderer`, and `processing` are not child parts. |
| P2 | `ChannelMapping.logical`, `binding.py:62` | Validation compares this “channel” to stream names. Clarify whether this is a stream map or a channel map and name/address both levels consistently. |
| P3 | `Sequence`, `sequence.py:14` | Same name as `collections.abc.Sequence` and `typing.Sequence`, but is a timed event document. `EventSequence` would be clearer in direct imports and annotations. |
| P3 | `compile`, `sfz.py:139` | Shadows Python's builtin in direct imports. `compile_instrument` describes its result; qualified `sfz.compile` is already clear, so weigh actual call style before renaming. |
| P3 | `Input`, `samples/enums.py:57`, versus `interface.Input` | One is a crossfade source kind, the other a public port. A domain-specific enum name avoids confusing collisions. Likewise distinguish declaration `Control` from animation control generators. |
| P3 | `Key`, `base.py:34` | Means an unrestricted integer musical key, not a keyboard key, dictionary key, or identifier. Prefer an explicit musical term at cross-domain boundaries. |
| P3 | `TrackSpec`, `BusSpec`, `ClipSpec`, `RouteSpec`, `arrangement.py` | All objects here are declarative, yet `Spec` appears on only some. `ControlClip` lacks it. Short domain names would be consistent unless a real same-module distinction requires the suffix. |
| P3 | `SemanticTrace`, `TraceSnapshot`, `synth_trace.py` and `samples/trace.py` | “Semantic” supplies little distinction in a definition library, while two direct imports collide. Choose a consistent module-qualified API or meaningful sample/synth prefixes; do not add both styles as aliases. The synth snapshot subclass is currently empty. |
| P3 | `Computed.limit`, `Tuning.detune`, `Oscillator.key_scale` | Units/meaning are hidden: denominator bound, cents, and dB per twelve note steps respectively. Prefer names exposing these specific quantities. |
| P3 | `RatioTable.desc`, `tuning.py:43` | Inconsistent with `description` elsewhere; saving four letters adds vocabulary. `name` here also differs from the containing score's name. Explain ownership or consolidate metadata. |
| P3 | `SfzReadResult`, `SfzWriteResult` | Functions compile from supplied facts and emit text without reading/writing files. Result names imply I/O; compilation/export terminology matches the ownership boundary. |
| P3 | `recs` wire marker and SFZ “Generated by recs” | `format='recs'` is explicitly retained intentionally, so it is not a parser defect. The generated-by attribution is misleading for Ufor. Separate historical wire identifiers from current producer identity. |

## Organization, feature overlap, and documentation

### 29. Shared instrument concepts are owned by the samples package

**P3, design concern.** [synth.py imports](../ufor/synth.py#L15),
[instrument_trace.py:9](../ufor/instrument_trace.py#L9).

Synth definitions and the shared lifecycle depend on `samples.enums`,
`samples.selection`, `samples.controls`, `samples.processing`, and
`samples.playback.Mapping`. Discovering reusable concepts requires navigating a
sample-specific namespace, and changes risk accidental sample-only assumptions.
Identify the genuinely common instrument model before any future organization
change; keep slices and sample traversal in the samples package.

### 30. Sample and synth lifecycle algorithms are duplicated

**P2, maintenance concern with existing shared defects.**
[sample preparer](../ufor/samples/trace.py#L71),
[synth preparer](../ufor/synth_trace.py#L60).

Selection-specific details differ, but sustain transitions, trigger lookup,
retirement, voice policy, and snapshot logic are copied. The same choke, layering,
pitch, control-validation, and coordinate defects occur in both. Shared action
classes alone do not ensure shared behavior. Establish common lifecycle
conformance cases for both before deciding how much implementation to share.

### 31. Module boundaries make related features hard to discover

**P3, design concern.** `effects.py` contains light-only effect definitions despite
its generic name; light behavior is spread across `effects`, `lights`,
`light_animation`, and `light_math`. `playback.py` plans event sequences, whereas
`samples/playback.py` defines sample traversal. `references.py` contains only
`RecordSelector`, while score references live in `interface.py` and recursive
reference traversal lives in `library.py`. `sfz.py` combines parsing, metadata,
compilation, export, and unsupported-feature reporting in about 1,750 lines.

Add a concise module/API map first. If reorganizing later, use actual ownership
boundaries, not merely file size, and update consumers in one coherent cutover.

### 32. Related control and envelope concepts need a single comparison guide

**P2, documentation/API concern.**
[automation.py](../ufor/automation.py), [envelope.py](../ufor/envelope.py),
[modulation.py](../ufor/modulation.py), [binding.py](../ufor/binding.py).

Users must choose among `TimelineCurve`, autonomous `Curve`, triggered `Envelope`,
LFO, modulation `Route`, and binding `ParameterMapping`. They differ in clock,
activation, endpoint policy, units, and ownership. Stepwise interpolation is named
`hold` in automation and `step` in modulation. These are not necessarily redundant
features, but the API does not present a clear decision guide. Document their
differences and shared rules before considering consolidation.

### 33. Current implementation claims conflict across documents

**P2, confirmed.** [sample-performance.md](../doc/sample-performance.md#L19)
describes semantic preparation as implemented, while
[instrument-format.md:498](../doc/instrument-format.md#L498) and
[modulation-format.md:303](../doc/modulation-format.md#L303) still describe voice
preparation as deferred. Composition documentation says random/shuffle execution
awaits an algorithm even though selection code now exists. README says video is
outside scope, while slideshow documentation and `VisualKind.video` support it.

Publish one capability matrix separating accepted definitions, validated
composition, implemented reference preparation, and host rendering. Link other
documents to it and keep deferred behavior out of claims of complete preparation.

### 34. The documented schema-generation entry point does not exist

**P2, confirmed.** [musical-format.md:138](../doc/musical-format.md#L138)
names `ufor.codec.document_schema`; the actual function is
[`score_schema`](../ufor/codec.py#L73). Correct the reference. The existing test
comparing the checked-in schema with generated output is useful and should remain;
the issue is the public regeneration instruction, not absence of a schema test.

### 35. Validation rules are stronger than the generated schema communicates

**P2, portability concern.** [base.Identifier](../ufor/base.py#L15),
[selector validators](../ufor/selector.py), and cross-field validators throughout.

Custom Python validators enforce identifier spelling, selector/tag grammar,
reference existence, and cross-field contracts not fully described by JSON
Schema. For example, `Identifier` uses an `AfterValidator` rather than a schema
pattern. A non-Python consumer can pass schema validation while Python rejects
the score. Document the schema as structural validation, publish the remaining
normative rules, and add language-neutral rejected cases. Also decide whether
Unicode lowercase/digit behavior is intentional for portable identifiers.

### 36. Current tests do not cover several semantic boundaries above

**P2, targeted coverage concern.** [sample tests](../test/test_samples.py),
[synth tests](../test/test_synth.py), [composition tests](../test/test_composition.py).

Group inheritance is tested before serialization; the shuffle test checks bag
contents and one refill boundary for seed 42, leaving other refill draws uncovered.
Existing lifecycle cases do not
establish all choke modes, part isolation, multilayer same-key behavior, or
serialized synth settings. Add focused regression and portable conformance cases
alongside the corresponding fixes. Do not treat a passing suite or a model
round-trip equality assertion as proof that effective musical behavior survives.

## Suggested order

1. Resolve inheritance/serialization and selection defects (1–3), then prevent
   lossy SFZ exports (16).
2. Establish the supported trace contract and fix lifecycle behavior (4–13), with
   shared sample/synth cases; address spatial validation (15).
3. Fix interoperability and validation gaps, then reconcile capability documents.
4. Decide naming and organization changes separately, with explicit consumer
   cutovers. Do not couple a broad rename to the correctness fixes.

## Additional work beyond the prompt

None. This change records findings only.
