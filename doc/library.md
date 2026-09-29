# User score libraries

A library is a named directory of TOML and Python scores. Ufor reads it explicitly,
returns usable entries together with diagnostics, and resolves selected scores
through its existing composition model. It does not start playback.

## Create and read

```python
from pathlib import Path
from ufor.library_files import create_library, read_library

create_library('my library', Path('scores'), Path('library.toml'))
library = read_library(Path('library.toml'))
```

The root is relative to the configuration file, whose registrations look like:

```toml
[[libraries]]
name = "my library"
root = "scores"
```

Omit the configuration path to use `~/.config/ufor/library.toml`. Creation defaults
to the root `~/.config/ufor/scores` and preserves existing registrations and
comments. Reading a missing default configuration returns an empty collection;
an explicitly requested missing or malformed configuration raises an error.
Reading never creates files. A leading `~/` expands to the home directory.
Creation serializes concurrent writers with a sibling `.lock` file and atomically
replaces the configuration, so interrupted writes leave the previous version
readable. The lock file remains beside the configuration.

Files are visited in configuration order, then sorted relative address order.
Only `.toml` and `.py` files are candidates. Symlinks are skipped and reported;
other files can be assets. The configuration itself is excluded from discovery.
Library roots must be trusted local directories. Symlinks are skipped during
discovery, but concurrent filesystem changes can replace a checked path before
it is read; the reader does not provide a security boundary against a process
that can modify the root.

## Select scores

```python
entries = library.find('#frogs#lake')
entry = library.resolve('my library:pretty score#frogs#lake/pretty')
composition = library.composition('quiet frogs', {'brightness': 0.5})
```

A selector has optional library, name, tags and address, in that order:

```text
my library: pretty score #frogs #lake /pretty
my library:pretty score#frogs#lake/pretty
```

These are equivalent. Spaces adjacent to delimiters are ignored; internal name
spaces matter. Names and library names cannot contain `:`, `#` or `/`; tag values
also cannot contain whitespace. Score names cannot contain `.*`. Address components
cannot contain `:` or `#`, and `/` separates components. There is no quoting,
escaping, pattern matching or percent decoding in selectors. TOML string quotes
are still required when storing a selector in TOML.

All parts must match literally, with case preserved. Multiple tags mean AND.
Without a library prefix, lookup searches every registered library. Addresses
include their suffix, such as `/pretty.toml`; `/pretty` can match `/pretty.toml`
or `/pretty.py`, and is ambiguous if both exist. Addresses are relative to the
library root, not absolute operating-system paths; traversal is forbidden.

`find()` returns ready entries, including zero or several matches. `resolve()`
and dependencies require exactly one candidate in the complete index, then
require that candidate to be usable. A rejected entry never causes fallback to
another candidate. Failed files retain their address even when no metadata can
be recovered. Use `library.entries` to inspect all states and `library.diagnostics`
to explain failures. Entries are keyed by `library:/address.toml`.

## TOML scores and presets

Ordinary scores have `name`, required descriptive `title`, and optional `tags`.
A composition selects its parts through `ScoreReference`:

```toml
[[body.parts]]
name = "pond"
score = { selector = "my library:pretty score" }
parameters = { brightness = 0.4 }
```

A preset changes public parameter defaults, retaining the selected behavior:

```toml
format = "recs"
version = 4
kind = "preset"
name = "quiet frogs"
title = "Quiet frogs by the lake"
tags = ["#quiet"]
score = { selector = "my library:pretty score" }
parameters = { brightness = 0.25 }
```

## Motion uses

The [example Motion library](../examples/motions/library.toml) contains a sine
vibrato, a pulse, and a pluck contour. A Motion score may expose a named Hz
parameter for its cycle rate. A use supplies a public value, or inherits the
score's default. A Motion preset can change that default. Other body fields are
currently literal values, not public parameter targets.

Within an instrument voice's settings, a Motion use may reference a library
score:

```toml
[motions.vibrato]
score = { selector = "motions:vibrato" }
scope = "voice"
parameters = { speed = 6.0 }
```

Library-backed instruments are authored and validated with unresolved uses.
Before handing one to a renderer, resolve the selected score explicitly:

```python
from ufor.library_files import read_library

library = read_library(config_path)
instrument = library.materialize("my library:my instrument")
```

`materialize` returns a fully validated score with independent inline Motion
uses. It rejects unknown parameters, out-of-range values, and references to
non-Motion scores. Relative Motion references resolve from the containing
library score; selectors retain the library's ambiguity and digest checks. Each
materialized use records its resolved library identity and available source
digest; that provenance stays with a renderer snapshot of the prepared score.

Presets can select other presets. Callers can override the defaults within the
original parameter ranges. Unknown or out-of-range parameters reject the preset.
The preset supplies its own metadata, including tags. An empty preset can name
an existing tuning or other score without public parameters. Browsing a tuning
does not make it a playable composition part.

`ScoreReference` accepts exactly one `selector` or relative `path`, plus optional
`sha256` of the selected file's exact bytes. Relative paths resolve from the
referring file and cannot escape the root. A hash mismatch is an error, never a
hint to search for another file.

## Python scores

A file defines exactly one local subclass of a concrete Ufor score model:

```python
from ufor.musical import OscillatorScore
from ufor.oscillator import Oscillator


class Tone(OscillatorScore):
    name: str = 'triangle tone'
    title: str = 'A triangle oscillator'
    tags: list[str] = ['#tone']
    body: Oscillator = Oscillator()
```

Imported classes do not count. Ufor reads field defaults and validates them as a
native score description without calling the class constructor or playback
methods. Default factories do execute. Required fields must have defaults in the
subclass. Declare dependencies in the usual typed score fields, including a
preset's `score` field, so they participate in the same resolution graph.

The declared class is retained as `entry.python_class`. Host-specific methods
remain available, but the host defines when and how to instantiate or execute
them. Loading modules executes local user code; this reader is not a sandbox.
Keep helper modules outside the score root or in installed packages. Ufor does
not add library directories to `sys.path`. Module/declaration failures are
reported per file; user interruption propagates. Each explicit read loads fresh
file contents without generating bytecode caches. Concurrent Python score loads
use distinct temporary module names so their executions cannot collide.
`read_library` defaults to at most 10000 score files, 16 MiB per file
(including the configuration), 256 MiB read in total, and 100000 discovered
directory entries per library. `max_files`, `max_file_bytes`, and
`max_total_bytes` can lower or raise the first three limits. Exceeded score
limits produce `limit` diagnostics and a partial index; an oversized
configuration raises `ValueError`. File contents are read with a byte cap.
Executing trusted Python scores has no in-process time limit. A host requiring
one must run the read in an isolated process with its own deadline and resource
limits.

## Host integration and diagnostics

Try the checked example library, with light compositions, chained presets,
a tuning and a Python oscillator:

```python
library = read_library(Path('conformance/library/library.toml'))
composition = library.composition('pond')
for diagnostic in library.diagnostics:
    print(diagnostic.library, diagnostic.address, diagnostic.message)
```

Discovery precedes dependency resolution, so forward references work. On a cycle
`A -> B -> C -> A`, visited from A, C is rejected for closing the cycle; B and A
are blocked by unavailable dependencies. Independent scores continue loading.
Diagnostics include the referring field and the full cycle. An explicit reread
rebuilds the index after edits; there is no watcher or automatic retry.
Dependency chains are limited to 128 scores by default. A deeper chain receives
a `depth` diagnostic and its dependents are blocked. Pass `max_depth` to
`read_library` or `Library` to set a limit from 1 through 160.

An entry's `score` is its authored declaration. `resolved` is the native score
prepared for composition. `library.records` supplies the existing `Composition`
resolver with resolved dependencies. Internal normalized paths such as
`dependency_0.toml` belong only to that in-memory graph; save the authored score,
not those synthetic paths.

`entry.content_origin` identifies the entry owning the inherited body. For a
preset this is its ultimate base score. Hosts use that origin's registered root
and address to resolve relative media assets, and its `python_class` for an
inherited Python implementation. The preset's own class, metadata and file hash
remain attached to the preset entry. Ufor leaves device access, playback and the
Lyte port to their hosts.

The content origin is not an asset location. `ScoreReference.path` locates a
definition inside the library graph; an asset's discriminated `location`
describes how a host obtains media. Relative asset locations resolve from the
ultimate definition's content origin. Volume IDs, URLs, Git repositories, and
Python provider references remain explicit and are never rewritten from a score
reference or selector.
