# Rust SoundSettings and target resolution

Port the shared sound processing declarations and their target semantics to the
existing Rust `ufor` crate. Python and Rust should agree on portable definitions,
defaults, units, validation and target lookup while keeping idiomatic APIs in
each language. This milestone supplies typed facts a renderer can use during
preparation. Keep enge unchanged, including its dependency pins and tests.

## Contract and ownership

- `ufor/samples/processing.py` defines `Processing`, EQ bands, resonant filters,
  filter response, boundary, order and tolerance, and `SoundSettings` over the
  common generator, modulation, binding and event declarations.
- The base resolver knows `processing.amplitude` (ratio, default 1), volume,
  tuning, pan and stereo balance. It resolves EQ gain, frequency and resonance
  under `eq-<name>`, cutoff and Q under `filter-<name>`, and authored Envelope
  fields under `envelope` and `envelfo-<name>`. Envelope addresses use the
  existing zero-based `on-<index>-…` and `release-<index>-…` spelling.
  Finite segment durations use seconds or beats according to the Envelope
  clock. Captured approaches target `time_constant` in seconds.
- `ModulationSettings.local_references` checks generator/event relationships
  and matches each declared target's unit and default to the bound setting.
  `SoundSettings.sound_parameters` adds amplitude-envelope, domain, scope,
  multiplier and event-latching restrictions. `validate_controls` needs the
  instrument's real control declarations. Rust already has the route and
  binding types and a generator-aware validator that reports outstanding
  bindings, connections and targets.
- Python subclasses extend this lookup. `ufor/synth.py` supplies FM operator,
  edge and carrier targets and Yamaha controls. `ufor/audio_effects.py` supplies
  targets from actual effect processors. Sample settings and groups also
  compose effective settings. Inventory these callers and their inheritance
  and validation order before touching the shared Python path.
- Enge currently discovers supported targets, defaults, sample-rate filter
  limits and indices before invoking native route preparation. Those indices,
  DSP limits and renderer profiles are host facts. Shared lookup establishing
  that a target exists does not establish that a specific backend supports it.
  Generator execution belongs to engelfo. Resource loading, reference
  materialization, scheduling and resolved `pitch_hz` remain host contracts.

## Implementation stages

1. **Freeze the portable contract.** Inventory Python defaults, wire shapes,
   omission and null behavior, identifier and unit rules, record counts, and
   context-dependent validation. Trace sampler composition and source-specific
   target extensions to establish the boundary. Publish a contract inventory
   and add the shared cases below with Python coverage before using them to
   drive Rust. Bring discrepancies in acceptance or outputs back for a decision.
2. **Port processing declarations.** Extend `ufor::samples::processing`
   with validated types for the shared processing fields and nested EQ and
   resonant filter declarations. Reuse shared identifier and unit parsing and
   the bounded codec. Preserve declaration order, defaults, strict booleans,
   finite scalars, allowed enum values, and uniqueness within the EQ and
   filter lists. Keep filter tolerance, boundary and order as authored data.
   Establish portable Python parity without narrowing Python authoring syntax.
3. **Port the base target resolver.** Accept the existing typed
   `modulation::Target` and resolve against the actual settings and Envelope
   definitions. Return unit, canonical default and any constraint intrinsic
   to the target. Preserve exact duration internally and match the current
   scalar default conversion at the validation boundary. Distinguish a known
   invalid address from an outstanding check that needs a specific reference
   or owner. Validate unit, default, domain and scope in the context that
   supplies them. The lookup must preserve address spelling and must not
   clamp an authored cutoff or assign a runtime index.
4. **Assemble and validate SoundSettings.** Decode the existing settings body
   with `processing`, optional amplitude Envelope and the shared modulation
   fields. Reuse generator-aware checks for source/output/range/release and
   event ports and control checks where declarations are available. Combine
   resolved targets and remaining requirements in declaration order. Preserve
   amplitude Envelope voice scope and unipolar levels, nonnegative amplitude
   domains and multipliers, positive resonance/Q domains, Envelope scope
   matching, and key/velocity-only latching for generator parameter routes.
   Test authoring references before and after the caller supplies the concrete
   body. Provide a clear preparation result for callers that require all
   applicable checks to be satisfied.
5. **Qualify and document.** Run the same fixtures through both implementations
   and through JSON and TOML where representable. Check construction and
   round-trip behavior and rerun tuning, modulation, generator, synth and
   sample contract regressions. Document public Rust APIs, Python authoring
   and portable validation, and what remains owner-specific. Apply the repo's
   Python/Rust checks. Use existing CI for available platform qualification.
   Record any later enge adoption as separate consumer work.

## Shared conformance cases

Use one new language-neutral `conformance/sound-settings.json` corpus with
named cases, canonical inputs, optional validation context, and expected
normalized values, resolved facts, outstanding checks or rejection categories.
Reuse examples and regression expectations from `modulation.json`,
`envelfo-scores-bindings.json`, `instrument.json` and `synth-instrument.json`
where they cover the same rules. Assert stable meaning rather than matching
exception text. Use exact comparisons for rationals, identifiers, enums,
ordering and defaults where representable. Use a documented tolerance for
arithmetic conversions where both languages legitimately round.

| Area | Cases |
|---|---|
| Defaults and wire | Empty processing/settings, explicit defaults and non-default values, declaration order, JSON/TOML round trips, omission versus JSON null for optional Envelope and references. |
| Processing validation | All four filter responses, both boundaries and orders, one/two stages, default and custom tolerance, canonical Hz/dB/cents values, duplicate names within one family, same name across EQ and filter, bad numeric types, nonfinite/range failures and unknown fields. |
| Base targets | All five processing targets with actual defaults, all EQ/filter target fields, separate EQ/filter namespaces, unknown name or parameter, unit and default mismatch. Resolve declarations without a device rate, including a cutoff that a particular host would need to clamp or reject. |
| Envelope targets | Main versus named Envelope, on/release and exact index, seconds/beats durations, captured `time_constant`, wrong phase/index/kind, indefinite hold, wrong scope, key/velocity success and control/generator source rejection. |
| Domains and composition | Amplitude minimum zero versus negative, zero versus positive resonance/Q minimum, negative multiply rejection, valid signed additive modulation, and invalid route/parameter scope or unit inherited from the modulation validator. |
| Control and reference context | Missing control context versus supplied context without the named control, polarity/domain mismatch, missing local generator versus an external reference, known reference scope mismatch, then materialization with compatible or incompatible target/default. Cover generator event ports and release checks through the existing validator. |
| Ownership | Follower rejection in base SoundSettings, unsupported extension address, and explicit outstanding target in partial owner validation. Existing FM, Yamaha, sample inheritance and effect target behavior stays covered by its Python fixtures. |
| Limits | Limit and limit-plus-one cases for combined nested records, early failure before expanding large lists, per-operation override, and separate character, value and depth bounds. |

## Decisions before implementation

1. **Scope of the first port.** Start with shared `Processing`, base
   `SoundSettings` and its target families. Inventory FM, Yamaha, effective
   sampler settings and effect graph extensions now, and port their typed
   owners in later milestones. Doing all target families at once would require
   porting substantial instrument/effect models before testing the base.
2. **Wire and Python authoring.** Preserve existing field names, defaults and
   target addresses. Use the existing JSON/TOML codec conventions for a
   settings-body API and Python's `context={'portable': True}` for shared
   validation, including revalidation of previously constructed objects.
   Keep the existing Python authoring coercions. A new score kind or global
   strict constructors would expand the compatibility change.
3. **Scalar syntax.** Reuse the approved portable scalar quantity grammar for
   Hz, dB, cents and dimensionless fields where their model already accepts
   quantity text. Keep strict numeric fields, booleans and literal stage counts
   strict. Use finite f64 scalars and checked i64 rational components for exact
   durations. Inventory Pydantic coercions and aliases first and decide any
   wire acceptance differences explicitly. Numeric-only interchange is
   simpler, but would diverge from adjacent shared declarations.
4. **Resolution result and extension seam.** Use a typed lookup result keyed
   by the existing target, derived from actual definitions. Expose the facts
   needed for matching unit/default and applying shared scope/domain rules.
   Keep the existing standalone generator-aware API and add base resolution
   in the new settings boundary. Require typed owner information before
   resolving owner-specific targets. An arbitrary catalog of caller-supplied
   defaults would be easy for hosts to provide but could bless nonexistent
   authored targets.
5. **Partial versus complete validation.** Allow structural authoring
   validation without instrument controls or loaded references, returning
   typed outstanding checks when information is missing. Require explicitly
   supplied controls and materialized target facts for complete preparation.
   Treat absent context differently from supplied context that contradicts a
   declaration. Rejecting all unresolved authoring input would simplify the
   API but would prevent the existing load-then-resolve workflow.
6. **DSP and spatial scope.** Port filter declarations and target constraints
   first. Keep sample-rate-specific cutoff preparation, biquad coefficients,
   panning laws, and conservative spatial bounds outside this milestone.
   Spatial bounds are shared mathematics but currently serve instrument-level
   composition, while coefficients and pan gains serve rendering. Folding
   them in would widen the conformance and ownership decisions.
7. **Preparation limits.** Reuse `PreparationLimits` with 10,000 records by
   default and a per-operation override. Count the root, present processing
   and Envelope declarations, EQ/filter entries, and all embedded generator,
   route, point, binding, event and supplied control records in one operation
   without counting the same authored record twice. Specify how nested
   tolerance objects count before freezing boundary fixtures. The existing
   record counter needs to account for the new settings branches. Preserve
   separate decoder limits. Independent per-section budgets would let one
   settings document exceed the intended combined bound.

## Completion

Complete when Rust and portable Python read the same base settings, resolve the
same target facts, report the same context still required, and agree on the
shared accept/reject cases. Keep public docs explicit about supported target
families. The milestone ends in uFor and requires no enge changes.

## Additional work beyond the prompt

None.
