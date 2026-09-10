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

Files are visited in configuration order, then sorted relative address order.
Only `.toml` and `.py` files are candidates. Symlinks are skipped and reported;
other files can be assets. The configuration itself is excluded from discovery.

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
A composition selects its parts through `ScoreVersion`:

```toml
[[body.parts]]
name = "pond"
score = { selector = "my library:pretty score" }
parameters = { brightness = 0.4 }
```

A preset changes public parameter defaults, retaining the selected behavior:

```toml
format = "recs"
version = 3
kind = "preset"
name = "quiet frogs"
title = "Quiet frogs by the lake"
tags = ["#quiet"]
score = { selector = "my library:pretty score" }
parameters = { brightness = 0.25 }
```

Presets can select other presets. Callers can override the defaults within the
original parameter ranges. Unknown or out-of-range parameters reject the preset.
The preset supplies its own metadata, including tags. An empty preset can name
an existing tuning or other score without public parameters. Browsing a tuning
does not make it a playable composition part.

`ScoreVersion` accepts exactly one `selector` or relative `path`, plus optional
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
file contents without generating bytecode caches.

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
