# Score composition implementation

The version 4 composition profile is implemented in `ufor.interface` and
`ufor.composition.Composition`. The [design](composition-design.md) explains
instance and timing semantics; the [worked example](composition-example.md)
provides a complete score graph. This document describes the supported behavior,
not a checklist for reimplementing it.

## Supported profile

- Audio connections require matching physical rates and ordered channel layouts.
  Event clocks may differ when every converted timestamp is exactly representable
  as an integer tick. Conversion uses rational arithmetic and preserves ordering.
- Placement has speed one, origins align at zero, and evaluation positions are
  nonnegative. Stateful histories begin at zero. Composition does not implement
  tempo-map placement, time stretching, or external live input.
- Each input receives at most one connection or public forwarding binding.
  Required inputs must be supplied. Outputs may fan out; event merging is not
  implicit. Audio tracks and buses use their declared summing and gain rules.
- Definition and signal graphs must be acyclic. A child's outputs conservatively
  depend on all its connected inputs, including across public boundaries.
- Public parameters are numeric initialization values with inherited units,
  ranges, and defaults. An export may narrow a range or replace a default, but
  cannot widen the range, change the unit, or duplicate another export's target.
- Arrangement control clips place part-scoped numeric automation on a child
  parameter or an arrangement clip, bus, or route gain. One control clip may
  address each target. A score's own direct/add/multiply curves remain supported;
  logical gates and voice/instrument-scoped arrangement automation are rejected.

`evaluation_windows(start, end, outputs)` propagates one finite half-open request
through clips and exports. A later crop retains the preceding child history
needed for state reconstruction. The requested end already includes any desired
tail; clip and export boundaries still limit it. No release is fabricated at a
sequence end, and finite recording bounds cannot be extended by a longer request.

`performance_trace(end, start=0, outputs=None)` returns ordered `EventDelivery`
records for sample and synth inputs. It converts event clocks, checks supported
performance inputs, and preserves nested instance isolation. It does not invoke
`samples.trace.prepare` or `synth_trace.prepare`, select voices, or render audio.
It rejects sample random/shuffle selection sets even though the standalone sample
preparer supports them with an explicit seed. Event payloads absent from supplied
recording definitions require a host provider.

## Public bindings

Each public declaration contains its contract and internal binding together.
Inputs and outputs have separate name namespaces; each name is unique within
its collection.

| Score | Binding |
| --- | --- |
| Recording | `stream`, with optional consecutive zero-based audio `channels` |
| Sequence | `sequence = true` |
| Sample or synth instrument | `performance = true` input; `audio = true` output |
| Arrangement | Track/bus, child `{ part, input }`, or child `{ part, output }` |
| Light animation | `light = true` |
| Automation | `control = true` |

Track/bus bindings may include gain, normalization, and a finite window. A file
render destination selects a public output; referencing a child does not run
that child's destinations. A parameter binding is `{ name, parameter }`, distinct
from a port selection. Synth public parameter exports remain unsupported.

## Resolution and portability

A `Part.score` is either a complete inline score or a `ScoreReference` containing
exactly one `path` or `selector` and optional `sha256`. Inline definitions have no
independent file identity. Referenced definitions may be shared, while each part
owns independent state under its complete nested path.

Relative POSIX score paths resolve from their containing score. Parent traversal
may reach siblings within the declared package root; absolute paths, URLs, and
root escapes are invalid. Contradictory pins and reference cycles are errors.
`Composition` operates on supplied `ScoreRecord` values without file access.
The explicit `library_files.read_library` API handles local discovery and file
hashes, and `library` resolves selectors and presets. See [libraries](library.md).
Asset acquisition remains separate host work.

A content-pinned portable package needs measured SHA-256 identities for its score
references and finite media, with paths contained in the package. Ordinary valid
scores need not be fully pinned: finite `content` records may omit unmeasured
facts. Editing pinned bytes invalidates their digests. Exporters that rewrite
paths must recompute affected digests. Ufor validates supplied identities but
does not seal or export packages. The composition conformance package contains
synthetic asset metadata, not playable media.

## Validation and host execution

Local models check fields, names, references, bindings, and locally known
contracts. Composition revalidates supplied records, resolves interfaces and
configuration, checks required inputs and graph cycles, and checks compatible
clocks/layouts and known extents. Hosts acquire and verify actual payloads,
resolve capabilities, and execute the graph.

Recs' `recs.edit.nested` implements nested recording arrangements. Instrument
rendering belongs to a host engine; a definition or delivery trace alone is not
proof that a renderer supports its features. Light scores share the resolver;
see [light semantics](light-format.md) and [lyte integration](port-lyte.md).

## Version boundaries

The codec accepts score version 4. `codec.migrate_score_v3` explicitly converts
the former asset `path`, `byte_length`, and `sha256` fields into structured
`location` and `content`, then validates the result. It neither rewrites files
nor provides a general reader for all historical declarations. Earlier naming
schemes and port/source layouts must be updated explicitly; media payloads are
not changed by this metadata conversion. See [validation](validation.md).
