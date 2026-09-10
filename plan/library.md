# User score libraries

Status: proposed implementation plan. This document changes no library reader,
score schema or host application. Existing animation files need no compatibility
reader. Lyte integration remains separate; see [port-lyte.md](../doc/port-lyte.md).

## 1. Storage and configuration

A library is a named root directory, recursively containing `.toml` and `.py`
score files. The user-chosen **file** is the configuration file that registers
those roots, not a file containing an entire library.

Use an explicitly selected configuration file when supplied; otherwise use
`~/.config/ufor/library.toml`. Do not implicitly merge the two configurations.
An example local configuration is:

```toml
[[libraries]]
name = "my library"
root = "./scores"

[[libraries]]
name = "shared experiments"
root = "~/music/score-experiments"
```

Resolve relative roots against the configuration file's directory. Expand a
leading `~/` against the user's home directory. Do not expand shell commands or
environment-variable expressions. Store library names without the trailing
colon; that colon is selector punctuation. Registered names must be unique.

A create-library operation takes a library name, optional root and configuration
path. It creates the directory and adds the registration, preserving other
registrations. Its default root is `~/.config/ufor/scores`. Reading a missing
default configuration returns an empty library collection; explicitly requesting
a missing configuration is an error. Reading never creates directories or files.

Walk roots in configuration order, and files in sorted library-relative POSIX
address order. File modification times do not affect ordering. Include exactly
the `.toml` and `.py` suffixes, recursively. Do not follow symlinked files or
directories; report them as skipped rather than importing files outside the
selected tree or encountering filesystem loops. Files with other suffixes may
be assets and are not score candidates. Exclude the selected configuration file
itself if it happens to be inside a root.

An unreadable root is reported without preventing other registered libraries
from loading. An invalid configuration must be reported before scanning: there
is no reliable set of named roots to use in that case.

## 2. Score identity and metadata

Every entry has:

| Field | Meaning |
| --- | --- |
| `name` | The score's string name, including meaningful internal spaces. |
| `tags` | Zero or more tags, each including its leading `#`. |
| `address` | The actual file path relative to the root, prefixed with `/`. |
| `library` | The registered library name. |

The canonical address includes the suffix: `/bali/frog-pix.toml`, for example.
It is a library address, not an operating-system absolute path. Derive it from
discovery; do not store a second editable address inside the file. Entry identity
is `(library, address)`. Names and tags need not be globally unique.

Apply the user's naming conventions:

- A score name is nonempty, starts with neither `:`, `#` nor `/`, and contains
  no literal `.*` substring.
- A tag begins with `#`, has a nonempty remainder, and contains no whitespace.
- A library selector prefix contains exactly one colon, at its end. Consequently
  a registered library name is nonempty and contains no colon.
- An address begins with `/` and uses `/` between filesystem path components.

Do not case-fold, collapse internal spaces or derive names from filenames.
Store canonical names without surrounding whitespace. Treat duplicate tags as
one tag; preserve first occurrence order for display. Tag order is irrelevant
to matching.

Use the existing `Score.name` as the entry name and add `Score.tags`, defaulting
to an empty list. Keep `title` as the descriptive label it currently provides;
this change does not rename it or use it for lookup. The current schema requires
`title`, so that requirement remains. Do not use the restrictive internal `Identifier`
type for library score names. Part, parameter, input and output names keep their
existing rules.

## 3. Score selectors

A selector contains four optional parts, in this order:

```text
[library:] [name] [#tag ...] [/address]
```

The following must parse to the same selector:

```text
my library: pretty score #frogs #lake /bali/frog-pix
my library:pretty score#frogs#lake/bali/frog-pix
```

Their values are library `my library`, name `pretty score`, tags `#frogs` and
`#lake`, and address `/bali/frog-pix`. Trim separator-adjacent whitespace only.
The space inside `my library` and the one inside `pretty score` are meaningful.

Examples with omitted parts:

| Selector | Meaning |
| --- | --- |
| `my library:` | All entries in that library. |
| `pretty score` | Entries named exactly `pretty score`. |
| `#frogs#lake` | Entries having both tags. |
| `/bali/frog-pix.toml` | Entries at that exact address. |
| `my library:#frogs/bali/frog-pix` | Entries satisfying all three restrictions. |
| Empty string | All entries, for browsing. |

Every supplied part restricts the result: combine parts and tags with AND.
An omitted library searches all registered libraries, including for references
inside a score. There is no implicit preference for the referring library or
for the first configured library. This keeps selectors consistent between
browsing and saved references. Qualify a reference when names are ambiguous.

**Initial matching choice:** names, library names and tags are literal and
case-sensitive. Addresses are exact; an address with neither supported suffix
matches that stem followed by `.toml` or `.py`. Thus the user's extensionless
example selects `/bali/frog-pix.toml` or `/bali/frog-pix.py`, but is ambiguous if
both exist. This does not mean prefix matching: `/bali/frog` does not select
`/bali/frog-pix.toml`. Canonical addresses always retain their suffix.

Pattern matching has not been specified. Reserve `.*` rather than inventing
regular-expression or glob semantics. Before implementing the matcher, confirm
whether selectors should support `.*` patterns; this plan currently assumes
literal matching and the extensionless-address rule above.

### Delimiters inside values

The naming rules allow delimiters *inside* a name, for example `lake: morning`
or `frogs#2`. Rejecting those names would impose a new restriction. Use quoted
selector components when a literal delimiter would otherwise be structural:

```text
my library:"lake: morning"#frogs/bali/morning.toml
my library:"frogs#2"#lake/bali/frogs.toml
```

Use JSON-style double-quoted strings and escapes for component payloads. Quotes
are selector syntax, not part of the stored value. A tag payload containing a
delimiter can likewise be written `#"stage/left"`, selecting the stored tag
`#stage/left`. A quoted address payload follows its leading `/`. Library names
can be quoted before their terminating colon, but still cannot contain a colon.
Quoting does not relax the restrictions on name prefixes, `.*` or tag whitespace.

Outside quotes, `:` terminates an optional library prefix, `#` starts a tag,
and the first address `/` begins the final address payload. Subsequent slashes
are path separators. Reject malformed quotes, empty tags and parts in the wrong
order. Do not tokenize on spaces or require spaces between parts. Do not percent
decode addresses, interpret `..`, or let an address escape a registered root.
The parser returns structured values; the formatter emits an unambiguous
canonical selector, adding quotes only when necessary.

### Browsing versus a dependency

Browsing returns zero or more matches in deterministic order. Resolving a score
dependency requires exactly one candidate. Zero matches and multiple matches
are reported errors for the referring score; never pick the first match.

Resolve against the complete discovered metadata index so forward references
work. Retain the chosen `(library, address)` for that read. If a candidate is
later rejected, do not silently choose another match. The next explicit read
rebuilds the index; filesystem watching and automatic hot replacement are not
part of this implementation.

## 4. TOML entries

Support ordinary native scores and a small preset form. A native score can
describe new material or a composition using the existing `parts`, public
interfaces, parameter exports and domain body. Add tags to its header.

Use selectors wherever a library score selects another score:

```toml
[[body.parts]]
name = "pond"
score = { selector = "my library:pretty score#frogs#lake" }
parameters = { brightness = 0.4 }
```

A preset names an existing score and supplies settings for its existing public
parameters. It is not a recursive merge of arbitrary TOML tables:

```toml
format = "recs"
version = 3
kind = "preset"
name = "quiet frogs"
title = "Quiet frogs by the lake"
tags = ["#frogs", "#lake", "#quiet"]
score = { selector = "my library:pretty score" }
parameters = { brightness = 0.25 }
```

A preset inherits its selected score's interface and behavior. Its parameters
change the configured public defaults; a caller can still override them within
the inherited ranges. Presets may select presets. Resolve the chain without
mutating its source scores. Unknown parameters and invalid values are errors.
Retain the preset's own name and tags; do not silently inherit tags and change
selector results. Support structured settings only through the corresponding
typed score fields or a later explicit parameter-model change.

## 5. Python entries

A `.py` entry defines exactly one discoverable score class. Imported classes
do not count. Zero or multiple locally defined score classes produce a diagnostic
for that file; do not introduce `:ClassName` address suffixes, since colon already
identifies a library.

Use the common Ufor score-class contract: the class declares the same score
metadata, public interface, settings and selector-bearing references as its
equivalent TOML description. In the simple case it subclasses an existing
concrete score model with usable defaults. The Python class name is not the
library name of the score. Its `name` and `tags` defaults supply that metadata;
its discovered file supplies the address.

A class can also provide a host implementation. Preserve the class object in
the loaded entry instead of reducing it to TOML and losing its methods. The
library does not call `render`, start playback, allocate devices or guess an
execution protocol from method names. The relevant host validates its supported
score-class protocol when preparing playback. Define that host contract during
the host port, keeping runtime state separate from the shared score description.

Dependency discovery must use declared selector-bearing fields. Do not let
constructors or rendering methods perform undeclared recursive library lookups.
This makes the same graph and cycle policy apply to TOML and Python entries.
Inspect class defaults and validate its description before constructing runtime
state. Python-generated descriptions must expose their dependencies before
they are prepared for execution.

Loading a Python module executes Python code. Configuring a library containing
Python is a choice to load local user code; the loader is not a sandbox. Only
import discovered files from explicitly registered roots. This does not restore
arbitrary Python import paths inside portable TOML scores. Keep ordinary module
imports separate from score selectors and do not add roots to global `sys.path`.

Load modules under names derived from their library/address identity, so equal
filenames in different directories or libraries do not collide. During one
read, import each file once. Import and declaration failures become diagnostics
for that entry, and reading continues. Do not catch user interruption. Helper
modules should live outside the score root or in an installed package; every
discovered `.py` file is otherwise treated as a candidate score.

## 6. Loading and circular references

Use a fresh index for each explicit read:

1. Discover all candidates in the stable order defined above.
2. Read metadata and declarations, reporting malformed entries individually.
3. Resolve each declared selector against the complete metadata index. Report
   missing and ambiguous dependencies against the referring file and field.
4. Visit candidates in discovery order, recursively visiting their dependencies
   in model field order, preserving list order and sorting dictionary keys.
   Maintain an active stack and completed-entry states.
5. Validate and publish usable scores. Return the usable entries and diagnostics
   together, rather than aborting the whole read on one score failure.

**When the current score refers to an entry already on the active stack, reject
the current score: it is the most recently entered score that revealed the
cycle.** This means loading order, not the newest filesystem modification time.
Do not reject a previously completed score, remove an arbitrary edge, or delete
any file. Report the closing selector and the entire cycle by library/address.

For example, with `A` selecting `B`, `B` selecting `C`, and `C` selecting `A`,
and traversal starting at `A`:

```text
active stack: A, B, C
closing reference: C selects A
cycle rejection: C
```

`C` is the one rejected for introducing the cycle. `B` and `A` cannot be prepared
because a required dependency is unavailable. Keep their declarations and
report them as blocked by that rejected dependency, rather than attributing
additional cycles to them or pretending they are executable. Continue with the
next independent candidate. A self-reference rejects that score directly.
Cross-library cycles use the same stack of `(library, address)` identities.

Resolve each entry at most once per read; a rejected or blocked entry is not
retried through a different root of the same traversal. Report one primary
cycle diagnostic and a dependency diagnostic for each blocked score. Fixing a
file and reading again can make all of them available.

The same distinction applies to missing files, invalid settings and failed
Python imports: reject the failing entry, report affected dependents, and retain
unrelated valid entries. Do not silently omit a required part from a composition.

## 7. Fit with existing Ufor structures

Reuse the current concepts rather than making a second composition model:

- Add `Score.tags` and metadata validation. Keep `name` distinct from `title` and
  from internal part names.
- Add a parsed `ScoreSelector` value with optional library, name and address,
  plus a tag list. Store selectors as strings in authored TOML and parse once.
- Extend `ScoreVersion` to select by either existing relative `path` or a
  `selector`, exactly one, with its existing optional `sha256`. A relative path
  remains useful for standalone score files; library authors use selectors.
  Both forms converge on one resolved entry, not separate loading pipelines.
- Apply selector support to every field that already uses `ScoreVersion`, not
  only animation parts. Keep `InputSelection` and `OutputSelection` unchanged:
  they select a particular part's interface, not a library score.
- Derive dependencies from actual score references, including the new preset
  reference. Do not add a second hand-maintained dependency list.
- Normalize accepted TOML presets and references for the existing `Composition`
  resolver. Keep its cycle errors for directly supplied invalid graphs; library
  loading adds per-entry recovery before calling it.
- Preserve optional version hashes as checks on the selected file's exact bytes.
  A hash mismatch rejects that reference; it is not a search hint or fallback.
  The hash of a Python file does not pin all of its imported dependencies.

Library indexing must support scores without public inputs or outputs, such as
tunings and scales. Being browseable does not imply being an instantiable part.
Validate those uses through the existing domain rules after selection.

Keep selector parsing, matching, declarations and dependency analysis in Ufor.
Put filesystem reading and Python importing behind an explicit reader boundary;
importing Ufor must never scan user directories. Hosts choose when to create or
read libraries and how to display their diagnostics.

## 8. Implementation sequence and acceptance tests

1. Specify and test selector parsing, formatting and matching. Include the two
   equivalent user examples, meaningful internal spaces, omitted parts, repeated
   tags, quoted delimiters, exact addresses and extensionless ambiguity. Resolve
   the pattern-matching question before this step is implemented.
2. Add configuration and metadata models, tags, selector-bearing `ScoreVersion`
   and preset declarations. Update schema, TOML round trips and documentation.
3. Build deterministic discovery and indexing with temporary-directory tests.
   Cover local/default configuration, paths relative to configuration, multiple
   roots, nested files, duplicate display names and unreadable entries.
4. Implement selector resolution and per-entry dependency analysis. Cover forward
   references, ambiguity, self-cycles, longer cycles, cross-library cycles,
   deterministic rejection, blocked dependents and continued loading of good
   scores. Verify that rejection never changes lookup into a silent fallback.
5. Add explicit Python loading and class discovery. Cover one declared class,
   imported classes, duplicate filenames, syntax/import/declaration failures and
   declared dependencies. Verify that indexing does not invoke playback methods.
6. Normalize usable entries for existing composition and domain validation.
   Test preset chains and overrides, missing public parameters, optional hashes,
   a new composition of selected scores and selection of a non-playable tuning.
7. Add language-neutral selector/index fixtures and runnable host integration
   examples. Host playback and the Lyte port happen in their own context; do not
   change Lyte while implementing this Ufor library plan.

Do not add a database, filesystem watcher, remote registry, network fetching,
plugin installer or backward-compatibility reader. A configuration file, an
explicit directory read and an in-memory index are sufficient.

## Additional work beyond the prompt

None.
