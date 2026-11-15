# Rust modulation and control definitions

## Goal and ownership

Extend the existing `ufor` Rust crate with the shared modulation-routing and
control-definition contract. Python and Rust should accept the same portable
definitions and produce equivalent scalar reference results, with idiomatic APIs
in each language. This follows [the tuning port](rust-tuning.md).

The immediate benefit for enge is a native definition and validation layer for
its synth, sampler and effect preparation. Its Rust DSP already has route maps,
control banks and generator integration; this is not a proposal to implement
them again. Replacing enge's Python preparation is a separate integration task.

**Enge remains unchanged throughout this plan.** Do not edit its code, manifests,
lockfiles, plans, fixtures or native interfaces. Do not migrate its array/tuple
layouts, replace its control runtime, or make uFor depend on enge. If implementation
would require a coordinated enge change, stop and identify that dependency for a
later task. Existing enge source is read-only contract evidence.

Ownership remains:

| Project | Responsibility |
|---|---|
| uFor | Portable definitions, validation, unit normalization and scalar format mathematics |
| enge | Audio realization, preparation adapters, indexed runtime plans, smoothing execution, addressed contexts, queues and callback storage |
| enveLFO | Stateful generator and Patch execution, observation schedules and generator continuation |
| Hosts | Device/controller protocols, clock acquisition, instance lifetimes and application policy |

Do not add audio generation, a new modulation scheduler, Python bindings,
WebAssembly packaging, device access, or a standalone enge executable.

## Scope and dependencies

Start from the current definitions, not the numeric layouts of one engine:

| Python source | Planned Rust coverage |
|---|---|
| `ufor/modulation.py` | `Unit`, `Operation`, `Interpolation`, `Target`, `Parameter`, `Source`, `Point`, `Route`, `Modulation`, `SourceValue`, `ParameterValue`; mapping and scalar combination |
| `ufor/control.py` | Scope/polarity declarations needed by this slice; no transport or generator execution |
| `ufor/samples/controls.py` | `ControlDeclaration` and source-domain validation |
| `ufor/samples/processing.py` | Binding value types: `EventBinding`, `ControlBinding`, `GeneratorBinding`, `FollowerBinding`, and `ReleaseTiming`; contextual validation only to the agreed cutline |
| `ufor/base.py` | Existing identifier semantics and finite scalar validation |

Use modules in `crates/ufor/src`, with public symbols imported from their defining
modules. Prefer `modulation`, `control`, `samples::controls` and
`samples::processing` as the corresponding module paths. Reuse the crate's
existing errors, checked numbers, Serde and JSON/TOML conventions. Do not add a
second crate, generic document registry or new root re-exports for this port.

Reuse code where its contract matches. In particular, the tuning parser's exact
pitch expressions and positivity requirements are not automatically appropriate
for signed dB amounts, general f64 scalar quantities or exact smoothing durations.
Do not change the existing tuning contract to accommodate this domain.

Keep Rust independent of Python, NumPy, Pint, enge and generator execution.
Dependency additions require a concrete need and separate commits; this plan
does not choose a new dependency.

## Contract inventory

Read `doc/modulation-format.md`, the modulation-route sections of
`doc/instrument-format.md`, `doc/validation.md`, and the source modules above.
Inventory existing tests in `test/test_instrument_document.py`,
`test/test_control_evolution.py`, `test/test_envelfo.py`, `test/test_effects.py`,
`test/test_synth.py` and `test/test_units.py`. Reuse relevant expectations from
`conformance/instrument.json`, `control-evolution.json` and `synth-instrument.json`;
do not bring unrelated instrument lifecycle or audio rendering into the runner.

Important current semantics to preserve or explicitly decide:

- A parameter target is the structured pair `{name, parameter}`. Source IDs,
  route IDs and parameter targets are independently unique.
- Parameter scopes are `voice`, `instrument` and `part`; source scopes additionally
  include `trigger`. Do not silently collapse these sets into one enum.
- A parameter requires `minimum <= default <= maximum`. Hz domains are positive,
  seconds/beats nonnegative, and normalized domains remain within `[-1, 1]`.
  Other unit names do not imply extra clipping or Boolean quantization.
- Source bounds are ordered; equal minimum/maximum is currently valid. A route
  needs at least one point, strictly increasing input coordinates and positive
  amounts for exponential interpolation.
- Additive routes use the target unit; multiplying routes use `ratio`. There is
  no implicit cents/Hz/dB conversion. Route knots must lie inside the source domain.
- The current cross-scope restriction rejects a non-instrument source driving
  an instrument parameter. Do not invent additional scope restrictions while porting.
- Mapping clamps outside its knots, including single-point constant mappings.
  A step changes at the knot itself. This endpoint clamping is distinct from
  rejecting a supplied source value outside its declared source domain.
- Evaluation validates supplied source names/domains, including unused supplied
  sources. Every routed source must be supplied; unused declared sources need not
  be. Base overrides must be unique, known and within their parameter domains.
- Routes reduce in `(source ID, route ID)` order. Parameter results retain
  parameter declaration order. Reordering route declarations does not select a
  winning route or change the prescribed reduction order.
- After mapping, weight `w` turns additive amount `a` into `w*a` and multiplier
  `m` into `1+w*(m-1)`. Compute `(base + sum(additions)) * product(multipliers)`.
  Defaults and explicit base overrides are distinct inputs.
- Addition currently uses Python `math.fsum`; multiplication follows the stable
  route order. A plain Rust `Iterator::sum` is not sufficient evidence of parity.
- Portable scalar fields accept JSON integer or floating number spellings as
  f64 values, not booleans or nonfinite values. Keep current Python coercions
  separately characterized and approve numeric-string/unit syntax explicitly.
- Final out-of-domain values are errors, with no implicit clipping. Inventory
  raw overflow/nonfinite behavior in standalone `map_value` and `evaluate`
  before making those failures part of the portable contract.

Identifier validation must preserve the existing Unicode Lowercase and
Decimal/Digit rules described in `doc/validation.md`. Generic alphanumeric tests
would accept a different language. Do not silently restrict identifiers to ASCII,
normalize them, or change their ordering. Record any implementation dependency
needed to match those properties before adding it.

## Implementation stages

### 1. Inventory, decisions and Python baseline cases

Resolve the decision register below before implementing affected behavior.
Create `conformance/modulation.json` and a focused Python conformance runner.
Separate current characterization from approved targets whenever they differ;
do not bless quirks by generating expected values from one implementation.

Cover definitions, scalar evaluation, units, bindings and budgets with explicit
expected values or deliberate error categories. Record the approved limits and
unit spellings in the fixture. No enge import or native audio backend is needed.

### 2. Core Rust definitions and validated interchange

Implement the modulation enums and models, finite-number checks, identifiers,
constructor validation, uniqueness, references, units and scope rules. Use
private invariant-bearing fields and validated deserialization, following the
tuning implementation. Edits construct a new validated Rust definition.

Support standalone JSON/TOML values for the implemented types with existing
field names, defaults and unknown-field rejection. A modulation collection is
embedded data, not a new score kind: do not invent a `ModulationScore`, envelope,
schema discriminator, version bump or placeholder instrument document.

### 3. Scalar mapping and combination

Implement linear, step and exponential mapping, source activation weights,
base overrides, stable reduction order and final-domain checks. Implement the
agreed cancellation-sensitive f64 sum deliberately. Preserve operation order;
do not regroup additions with the base or combine products algebraically.

Return deliberate Rust errors for invalid input, arithmetic range failures and
domain failures. Align the Python portable path in the same stage where its
behavior differs. This is a scalar reference API and preparation facility,
not an allocation-free audio callback implementation or performance guarantee.

### 4. Control declarations and binding value types

Implement unipolar/bipolar declarations and default validation. Port binding
fields, discriminator values and defaults, including key/velocity variants,
exact nonnegative smoothing (`1/200` second by default), generator output
selection, release timing and follower processor references.

Apply binding-independent and locally available checks to the agreed subset:
unique binding names, matching source names, key/velocity source rules and
control-declaration compatibility where the enclosing declarations are supplied.
Use existing declaration containers rather than inventing another document shape.

Do not claim full `ModulationSettings` parity. Its validation also depends on
actual generator definitions, Patch outputs, signal ranges, releasing envelopes,
processor capabilities, event ports/cues and target parameter definitions. A
binding name alone cannot establish those facts. Keep those checks deferred
until their real definition contracts are available; do not add opaque payloads,
stub generators, fabricated metadata schemas or implicit successful resolution.

Do not port `ControlState`, `control_at`, `control_event`, `TempoMap`, transport
seek handling or Envelfo event execution in this milestone. Shared control-ramp
traces are evidence for a later runtime port, not proof of runtime support here.

### 5. Python portable alignment and documentation

Use the established `context={'portable': True}` approach for affected portable
validation, including nested values and existing-instance revalidation where
needed. Preserve separately documented Python authoring coercions and broader
Pint facilities. Do not change global clocks, exact timeline arithmetic, or
unrelated model validation to implement a binding duration.

Review all callers of any shared Python helper being changed, including light
animation, synth, samples and effect definitions. Preserve existing valid
contracts, serialization and public entry points so this work does not require
an enge update. If that is impossible, report the dependency before proceeding.

Replace superseded characterization and expected failures once both languages
pass the approved cases. Update the public Rust coverage guide, format and
validation documents, and generated schema if model constraints change. Keep
the remaining plan limited to unfinished work.

### 6. Verification and completion

Both suites must read the same checked-in cases. Run locked Cargo tests,
formatting and Clippy. For Python/data changes run the repository's pytest,
Ruff, formatting, type checking, pyupgrade and diff checks against the installed
non-editable package. Keep any necessary development tooling in version control.

Use the existing release-only macOS, Windows and Linux matrix for Python 3.13,
Rust 1.85 and stable. Do not trigger workflows for every commit. Local checks
do not establish hosted results. No device, service or enge execution is required.

The implementation portion is complete when both languages pass the agreed
definition, scalar, binding-subset, unit and budget cases, round trips preserve
document values, and docs distinguish implemented checks from deferred contextual
resolution. Track hosted qualification separately until those jobs actually run.
No enge integration or new runtime capability is implied by that completion.

## Shared conformance cases

The new corpus should contain complete inputs, stable IDs, normalized definitions,
evaluations and expected errors. Compare strings, enums, ordering, exact rational
components and error categories exactly. Approximate scalar results initially use
absolute/relative tolerance `1e-12`; cancellation fixtures must also check their
specific small residual so a large relative tolerance cannot conceal its loss.

| Group | Required cases |
|---|---|
| Definitions | Empty modulation; defaults; constant source/parameter domains; every unit, scope and enum; nonempty/ordered points; unknown fields; duplicates and missing references |
| Parameter domains | Positive Hz; nonnegative durations; normalized bounds; invalid defaults; signed dB/cents/volts/radians without invented restrictions |
| Mapping | One point; both clamped endpoints; exact knot hits; linear midpoints; step boundaries; geometric midpoint; invalid exponential amounts |
| Evaluation inputs | Missing routed source; valid unused declaration; unknown or out-of-domain supplied source; invalid weights; unique/duplicate/unknown/out-of-domain base overrides |
| Combination | Zero and full activation; weight 0.5 with multiplier 0.2 gives 0.6; `(10 + 2 - 1) * 0.5 * 2 = 11`; multiple targets; route permutations; output order |
| Numeric behavior | Finite scientific literals; negative zero where observable; cancellation such as `1e16 + 1 - 1e16`; product order; overflow/nonfinite intermediates; final-domain failure without clipping |
| Identifiers | Existing accepted Unicode examples; invalid initials and digit categories; punctuation; no normalization; stable ID ordering |
| Units | Canonical values and every approved spelling; rational quantity text; incompatible dimensions; nonfinite values; Python-only authoring input normalized before portable validation |
| Bindings | All leaf discriminators/defaults; control polarity/defaults; exact smoothing and zero duration; negative/floating time rejection; key/velocity rules; local name matching; retained generator/follower references |
| Interchange and edits | JSON and TOML round trips; defaults/optional fields; authored unit normalization; valid reconstruction; invalid edited Python instance rejection at the agreed portable boundary |
| Budgets | Each agreed collection/string/aggregate limit at and above its boundary; existing codec character/value/depth limits; exact duration range and overflow |

Keep context-dependent generator/processor cases explicitly marked deferred,
not accepted by partial validation and not hidden behind passing placeholders.
Do not duplicate full enge audio or enveLFO execution corpora in uFor.

## Decisions before affected implementation

The following are recommendations for review, not approvals supplied by this plan.
The existing f64/i64 policy, independent Python/Rust implementations and unchanged
enge scope are already settled and do not need to be reopened.

| Decision | Recommendation | Consequence or alternative |
|---|---|---|
| Binding cutline | Port all binding leaf types, core modulation and control declarations; implement only checks supported by actual local declarations. Defer full `ModulationSettings` and generator/processor resolution. | Keeps the first port useful without pulling in instruments and generators. Full contextual parity would substantially expand the milestone. |
| Summation and errors | Preserve `fsum`-quality cancellation behavior with a tested f64 partial-sum algorithm, stable products and explicit range/domain errors. Reject nonfinite public scalar inputs deliberately. | Ordinary summation can lose audible control residuals. Promise shared cases/tolerances, not bit-identical transcendental results or unrestricted exact real summation. Characterize Python overflow before choosing its public error boundary. |
| Portable scalar unit grammar | Extend the tuning-specific subset only for these declared units, with an approved finite spelling/arithmetic table. Candidate examples include `6 dB`, `250 ms`, `1/4 beat`, `500 mV` and `1 radian`; dimensionless units use canonical numbers. Preserve broader Pint authoring. | Canonical numeric-only input is a smaller first implementation but does not provide authored-unit parity. Approve exact aliases and numeric grammar before implementing the adapter. Scalars remain f64; exact smoothing does not. |
| Exact smoothing representation | Reuse bounded i64 rational storage and existing seconds meaning; accept canonical integer/rational strings and approved exact second-unit spellings. No binary float times, i128 intermediates, or automatic frame/beat conversion. | Reuse of the tuning storage does not authorize its power grammar or pitch positivity rules for durations. General time/tempo facilities stay deferred. |
| Preparation budgets | Add explicit collection and total-record caps before implementation. Start review with 10,000 aggregate parameters, sources, routes, points, bindings and control declarations, plus 4096-character identifier/authored-quantity limits and existing document budgets. | These are new proposed modulation limits, not inherited tuning requirements. An aggregate cap avoids a per-route point limit multiplying into unbounded total work. Adjust against real definitions before approval. |
| Scope and identifier compatibility | Preserve the current asymmetric scope rules and Unicode identifier language. Review any discovered Python quirks explicitly. | Stricter ownership rules or ASCII-only identifiers would be behavior changes, not routine Rust typing choices. |
| Interchange surface | Reuse Serde and the existing Python model/context facilities for standalone and embedded values, with no new score kind. Decide whether named text adapters are needed after the API inventory. | Avoids parallel models and unsupported enclosing score schemas. Native consumer adoption remains a later enge task. |

Record decisions and their fixture changes together before writing dependent
Rust code. Ask immediately if new ambiguities affect musical behavior, validation,
data shape or ownership. Do not silently choose compatibility behavior merely
to make one language pass.

## Additional work beyond the prompt

None.
