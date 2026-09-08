# Ufor: Universal Format

Portable definitions for quantities and events in time, and the musical objects
that produce or transform them. The Python library contains models, validation,
TOML serialization, and pure mathematics. Applications own devices, UI, file
loading policy, capture, and audio generation.

The first document profiles come from Recs. Their existing `format = "recs"`
marker and version are preserved during extraction; the package name does not
silently rewrite existing recordings. A future format-identity cutover is a
separate explicit change.

Import public symbols from their defining modules, such as `ufor.time` and
`ufor.recording`. `ufor.codec` parses documents, writes TOML, and emits JSON
Schema. No Recs, Tuney, Reccy, NumPy, audio, or GUI dependency is required.

Run `uv sync`, `uv run pytest`, `uv run ruff check --select B,E,F,I ufor test`, and
`uv run ty check ufor` for development. Source code is MIT licensed;
definitions were extracted from Tom Ritchford's Recs and Tuney repositories.

Musical definitions and their language-neutral semantics are specified in
[Musical format](doc/musical-format.md). Machine-readable definitions are in
[schema/documents.json](schema/documents.json), with pitch conformance cases in
[conformance/pitch.json](conformance/pitch.json).

Recs and Tuney use this checkout as an editable sibling during development.
Their install metadata pins a public Ufor source archive, so release builds
can install it without GitHub SSH credentials.
