# Rust modulation and control definitions

## Goal and boundaries

Extend the existing `ufor` Rust crate with the shared modulation-routing and
control-definition contract. Python and Rust use the same portable definitions
and scalar mathematics with idiomatic APIs. This follows [the tuning port](rust-tuning.md).

The implementation is complete locally. See [the API and contract guide](../doc/rust-modulation.md),
`conformance/modulation.json`, `test/test_modulation_conformance.py` and
`crates/ufor/tests/modulation.rs`. Hosted qualification remains below.

This scalar milestone made no changes to enge code, manifests, lockfiles,
plans, fixtures, native interfaces, array layouts or control runtimes. Subsequent
generator integration is underway there; modulation integration remains a
separate consumer task.

Ownership remains:

| Project | Responsibility |
|---|---|
| uFor | Portable definitions, validation, unit normalization and scalar format mathematics |
| enge | Audio realization, preparation adapters, indexed runtime plans, smoothing execution, addressed contexts, queues and callback storage |
| enveLFO | Stateful generator/Patch execution, observation schedules and continuation |
| Hosts | Devices, controller protocols, clocks, instance lifetimes and application policy |

## Approved decisions

The user approved all seven recommendations on 2026-11-15, then approved the
concrete scalar grammar, pinned Unicode implementation and unresolved-binding
return value. No decisions are currently pending.

| Decision | Agreed contract and implementation |
|---|---|
| Binding cutline | All binding leaf types, core modulation and control declarations are implemented. Local checks use actual declarations and return unresolved generator/follower bindings in declaration order. They do not claim full `ModulationSettings` validation. |
| Summation and errors | F64 partial sums preserve the shared `fsum` cancellation/halfway cases. Products reduce in stable source/route order. Nonfinite public scalar inputs, arithmetic overflow and final-domain violations fail deliberately. No implicit clipping or algebraic regrouping. |
| Scalar units | Signed decimal/scientific literals and rational quotients, at most one compatible unit factor, without parentheses, addition, multiplication, powers or functions. The approved spelling table is in the API guide and shared cases. Scalars remain finite f64; broader Pint input is a Python authoring facility. |
| Exact smoothing | Nonnegative seconds in bounded i64 rational storage, canonical integer/rational/decimal/scientific text and the approved exact second-unit spellings. Default `1/200`; no binary float time, i128 fallback, beat/frame conversion or general tempo port. |
| Budgets | At most 10,000 aggregate parameters, sources, routes, points, supplied bindings and control declarations; 4096-character identifier/quantity text limits. Document adapters also enforce the existing character/value/depth budgets. |
| Scope and identifiers | Current asymmetric source/parameter scope rules are preserved. Portable identifiers use Python 3.13 / Unicode 15.1.0 property tables generated into tracked Python JSON and Rust source. Python authoring retains native Unicode behavior. |
| Interchange | Existing Serde and Python model/context facilities are reused. Native `parse_modulation` / `modulation_text` follow the existing tuning text-adapter convention. There is no new score kind, registry, wrapper document or version bump. |

The concrete unit spellings reuse the tuning Hz/cents aliases and add
dB/decibel/decibels, V/volt/volts, mV/millivolt/millivolts,
s/second/seconds, ms/millisecond/milliseconds, beat/beats and rad/radian/radians.
Dimensionless declared units use numeric text only. A bare compatible unit means
one unit; otherwise it follows a numeric quantity, before or after its quotient.

## Implemented stages and evidence

1. The contract inventory covered the current modulation/control/binding models,
   instrument rules, existing conformance data and current enge preparation as
   read-only evidence. Expectations were written from the contract, with Python
   used to check them, rather than generated from one backend's outputs.
2. Rust `modulation`, `control` and `identifier` modules implement validated enums,
   models, domains, point ordering, references, uniqueness, unit/scope compatibility
   and standalone JSON/TOML interchange. Invariant-bearing fields are private.
3. Scalar mapping and combination implement clamped knots, step boundaries,
   exponential interpolation, post-mapping weights, base overrides, accurate sums,
   ordered products and explicit errors. Output order follows parameter declarations.
4. `samples::controls` and `samples::processing` implement declarations and binding
   leaves. `validate_local_bindings` checks names, control domains/scopes, key and
   velocity rules, follower source rules and aggregate preparation size, returning
   references that still need external context.
5. Python portable validation uses `context={'portable': True}`, propagates to
   nested definitions and revalidates existing instances. Ordinary authoring
   coercions and broader Pint syntax remain. Schema and format/validation guides
   reflect the implemented limits and boundary.

The shared corpus covers normalized definitions and JSON/TOML round trips;
finite/invalid scalar inputs; units and exact smoothing; Unicode identifiers;
mapping endpoints, knots and midpoints; weighting, defaults and overrides;
missing/unused sources; duplicate/reference/scope/domain errors; cancellation and
halfway rounding; product overflow and route permutations; unresolved binding
status/order; and aggregate/text limits at and above their boundaries.

Scalar comparisons use the corpus's `1e-12` absolute/relative tolerances, with
exact residual assertions for cancellation cases and relative-only checks for
tiny finite quantities. These are not promises of bit-identical transcendental
results across platforms. The existing f64 weighting order is preserved: an
extremely small multiplier can round to zero in `1+w*(m-1)` even at full weight.

Regenerate both Unicode outputs using the tracked Python 3.13 generator:

```sh
uv run --python 3.13 --frozen --no-editable python schema/generate_identifiers.py
cargo fmt --all
```

## Remaining qualification

- Obtain hosted evidence from the existing release-only macOS, Windows and Linux
  matrix, with Python 3.13, Rust 1.85 and stable. Local native results do not
  establish those jobs have passed. Do not trigger workflows for every commit.
- Keep the current locked Cargo tests, formatting, Clippy and repository Python
  verification gates passing as this native contract grows. Python source/data
  checks use the installed non-editable package.

## Explicitly deferred contextual work

The subsequent [generator milestone](rust-envelfo.md) implements generator
definitions, Patch output resolution, releasing-envelope checks and known event
ports/cues in its separate generator-aware binding API. These are no longer
remaining shared-library work. Enge's completed adoption is documented in
[its integration record](https://github.com/rec/enge/blob/main/doc/rust-ufor-integration.md).

Full `ModulationSettings`, processor capabilities and validation against actual
instrument/processor target settings remain deferred. Local success and binding
leaf parsing do not establish those facts. Future validation must use their real
definitions; do not invent opaque payloads, stub generators or fabricated metadata
schemas to bypass the cutline.

`ControlState`, smoothing execution, `control_at`, `control_event`, `TempoMap`,
transport handling, audio generation, new schedulers, Python/Rust bindings,
WebAssembly, device access and an independent enge executable remain outside
this milestone. No native host integration or runtime performance guarantee is
implied by passing the uFor scalar corpus.

For any later change affecting musical behavior, validation, data shape or
ownership, ask immediately and record the decision with its shared cases.

## Additional work beyond the prompt

None.
