# Asset cache: verified objects, captures, and retention

Status: proposed host design, not an implemented API or score-format change.
Build acquisition and caching outside uFor. The cache accepts opaque finite
bytes, with audio-specific capture adapters layered above it.

## Critique of the original draft

The first draft left these implementation-blocking problems:

- HTTP freshness, validity of hash-pinned bytes, and deletion deadlines were
  conflated. Missing expiry headers and response variants were not addressed.
- Provider keys omitted resolved timebases, dependency/environment identity, and
  materialization settings. Pure output was confused with permanent retention.
- Ordered additive rules had no meaningful ordering. The example used a duration
  forbidden by its own grammar, and count-plus-age behavior was ambiguous.
- Space-pressure eviction could bypass an unspecified expiry condition, while
  references were only sometimes protected. Some entries had no collection rule.
- Any active reader would block all collection. Size checks alone could accept
  corrupted objects, and publication/collection races were unspecified.
- Stream capture omitted borrowed-buffer handling, bounded resource use, clean
  stopping, and an explicit way to choose a captured version for playback.
- Derivatives unnecessarily required a separate storage implementation. CLI and
  database choices were presented without establishing that either was needed.

The contracts below replace those parts of the draft.

## Scope and boundaries

Cover all eight source forms in [the location plan](url-paths.md): local files,
volume files, finite URLs, Git files, streaming URLs, complete-array providers,
callback providers, and client-buffer providers. Finite MIDI files, images,
SysEx, captions, and arbitrary binary files use the same storage path as audio.
MIME types and filename extensions are descriptive, not identities.

No new asset location or score field is required. A host resolves declarations
into verified objects or explicit captures. A sealed export copies content into
a package and writes finite uFor asset declarations. Private cache references
must never become portable score identities.

Initial implementation: one private filesystem store per OS user, accessed by
multiple cooperating host processes. Cross-user sharing, distributed eviction,
and a cache daemon are out of scope. Use atomic filesystem manifests and a
store-wide metadata lock initially; no database dependency is required. The
public interface is a host library; command examples below describe operations,
not a commitment to introduce a new executable in uFor.

## Identities and records

| Record | Identity and meaning |
| --- | --- |
| Object | SHA-256 plus byte length of an immutable stored byte sequence |
| Entry | Opaque immutable ID for one acquisition or materialization; points to an object |
| Capture | Opaque immutable ID for a finite session manifest and its ordered object dependencies |
| Source key | Versioned canonical source/request fingerprint, used to group acquisitions, never proof of equal bytes |
| Provider value key | Versioned fingerprint of the complete deterministic computation and materialization contract |
| Reference | Unique host-local name pointing to an entry or capture; an explicit retention root |
| Pin | Explicit retention root on an entry, capture, or object, optionally with a UTC expiry |
| Lease | Temporary root held by a live reader or writer |

Immutable entry facts include source key, object identity, creation time, media
kind, encoding, provenance, and verified observations. Access times, HTTP
validation state, and policy annotations are mutable side records. Capture
manifests and their dependency lists are immutable too.

A source key includes location, resolved context, expected content identity when
present, and relevant representation settings. Relative paths need the package
identity; volume paths need the volume ID; Python requests need resolved sample
rate and channel layout, not just a score-local timebase name. Do not normalize
URLs or provider values in ways that change their meaning. Canonicalization must
be versioned and have fixtures for null, booleans, integer versus float arguments,
Unicode, and dictionary ordering; forbid nonfinite numbers.

Use a host credential-scope ID to partition acquisition metadata. A content hash
is not authorization to access another scope's entry. Never keep raw credentials,
cookies, signed URLs, or secret provider arguments in ordinary metadata. Where a
secret affects lookup, use a keyed local fingerprint and resolve the actual value
from host configuration. A redacted display URL cannot be used as a lookup key.
Deduplication remains internal to the user's authorized store.

## Objects, publication, and recovery

```text
objects/sha256/<prefix>/<digest>    immutable payloads
entries/<id>.json                  immutable acquisition facts
captures/<id>.json                 immutable session manifests
state/                            access, HTTP state, references, pins, leases
staging/                          unpublished acquisitions and recordings
```

Write into staging on the same filesystem while computing SHA-256 and length.
For a declared finite asset, check both against `content` before publication.
An import of an arbitrary local file computes new facts instead. Verify existing
objects by hash before trusting or reusing them; equal length is insufficient.
Verified open handles may be reused during a process lifetime while the store
remains immutable. Corruption is an error: quarantine it and report affected
roots. Captures and imports may be irreplaceable, so never silently promise
re-acquisition after corruption.

Flush payloads and required directory updates before publishing manifests. The
metadata lock coordinates publication, lease acquisition, reference updates, and
collection. Concurrent writers of equal bytes converge on one object. Readers
acquire their lease before receiving a usable handle. Writers protect published
fragments until their capture manifest becomes the durable root.

A crash may leave an unreferenced object or staged file, never a usable manifest
pointing to unpublished bytes. Recovery checks dead process leases, incomplete
sessions, and orphaned objects. It does not reclaim a live lease merely because
a clock-based timeout elapsed. Dry-run recovery precedes deletion of incomplete
recordings. Metadata deletions are durable before their now-unreachable objects
are reclaimed.

Use original encoded bytes for finite sources. Generated arrays require a
specified lossless representation that preserves dtype, shape, sample values,
rate, and channel order. Quantization, resampling, and lossy encoding produce
explicit derivatives. Thumbnails, waveforms, and indexes can use the same object
store with `category = "derived"`; their keys include input identities and
transform settings/version. They do not require a second storage system.

## Behavior for every source

| Source | Automatic behavior | Explicit storage |
| --- | --- | --- |
| Relative file | Read and verify in place; no copy | Import an independent byte snapshot |
| Volume file | Resolve approved volume and verify in place; no copy | Import an independent byte snapshot |
| Download URL | Acquire and verify finite bytes; store if response policy permits | Retain or pin the resulting entry |
| Git file | Acquire commit/path-selected blob and verify content | Retain or pin the resulting entry |
| Streaming URL | Open a new live session; no automatic recording | Capture a bounded realization |
| Python buffer | Evaluate each time unless a deterministic contract is configured | Materialize finite output |
| Python callback | Open a new session; borrowed arrays | Capture through bounded client-owned buffers |
| Python client buffer | Open a new session; reuse client storage | Capture before reusing filled storage |

Direct reads do not create payload entries, and GC must never delete external
local or volume files. An import copies bytes, not a mutable hard link or symlink.
Verification and use must concern the same observed bytes; hosts cannot verify a
path and then blindly reopen a potentially changed file.

The existing Python provider protocol remains audio-specific. Other finite asset
types need no provider protocol change to be cached. Future typed generators can
supply bytes to the same store; this plan does not invent image/MIDI ndarray or
stream interfaces.

## HTTP: response freshness versus retained content

There are two distinct operations:

- Resolving an existing uFor asset requests its expected SHA-256 and length. A
  verified, authorized retained object satisfies that immutable request even if
  the acquisition URL has changed or become unavailable.
- Fetching a URL's current representation uses HTTP response caching rules. Its
  freshness says when a response can answer that request without validation.
  Changed bytes are a new acquisition, never an automatic score update.

HTTP expiration does not corrupt stored bytes or require their deletion. Retention
is a separate policy. A mutable URL lookup without a known hash is a host import
operation; current finite uFor assets still require `content`.

Follow [RFC 9111](https://www.rfc-editor.org/rfc/rfc9111.html) for response reuse:
use `Cache-Control` precedence, `Expires`, and corrected age including `Date`,
`Age`, and request/response timing. Default to immediate staleness without an
explicit lifetime; do not invent an expiry. `no-cache` requires validation;
`no-store` forbids automatic persistence; `must-revalidate` prevents prohibited
stale reuse. Match request variants through `Vary`; `Vary: *` prevents ordinary
reuse. Keep authenticated/private responses in their user and credential scope.
A matching `304` updates permitted metadata and recalculates freshness; it does
not necessarily make the response fresh. A `200` needs fresh byte verification.

No automatic stale-on-error fallback for current-URL requests. Offline hash-based
resolution succeeds only for content already admitted to the retained store;
otherwise it reports a cache miss. Pins do not override `no-store`. An explicit
user save is a separate archival operation, not an HTTP-cache policy exception.

Define the hashed payload as the file representation after HTTP content decoding,
before media decoding, consistent with the score's byte identity. Bound encoded
transfer size and decoded body size. Incomplete responses remain staged, and a
`304` without its complete stored body cannot satisfy acquisition. Preserve only
necessary response metadata and redact sensitive headers and URLs.

## Git acquisition

Keep repository origin, pinned full commit, path, observed blob ID, and verified
file content identity as separate facts. Git object IDs are not file SHA-256
identities. Reject symlink/submodule entries and unresolved LFS pointers as in the
location plan; do not run checkout hooks or repository code.

Use available Git objects or a filtered fetch when supported. Obtaining one path
can require commit/tree objects and a larger pack; do not promise single-object
transfer. Keep auxiliary Git transport data in a separately bounded area. Once
file bytes are verified and stored, retained use needs neither the repository nor
HTTP freshness. The transport cache uses its own GC without deleting asset
objects. See [Git partial clone](https://git-scm.com/docs/partial-clone).

## Deterministic provider values

A trusted host registration may assert a finite buffer provider is deterministic.
Statelessness and lack of randomness alone are insufficient: filesystem reads,
clock, environment, dependencies, and native libraries can affect output.
The contract identifies all relevant inputs and execution environment, or asserts
that output is independent of those excluded. uFor does not infer purity.

The value key contains provider identity and implementation/dependency version,
canonical effective arguments including defaults, resolved rate, ordered channels,
frame count, output dtype, provider protocol version, and materialization
format/encoder version and settings. An implementation version is a host-managed
contract covering dependencies, not merely a hash of the function's source.

Equal keys permit reuse without running the function. If repeated evaluations
produce different objects for one key, invalidate that mapping and report the
broken contract rather than silently replacing it. A deterministic value never
becomes stale with time, but it remains eligible for GC unless protected. A pin
or a `protect = "forever"` rule keeps it indefinitely. Reject admission if that
promise cannot fit the configured capacity.

Nondeterministic buffer output may be explicitly materialized as a new entry on
every call. Streaming providers remain session sources for automatic lookup; a
capture is an immutable result independent of whether it can be regenerated.

## Captures, versions, and memory ownership

A capture request supplies a source plus a frame/duration limit or a manual-stop
mode, always with a maximum byte budget. Automatic recording without a bound is
not a supported operation. Normal EOF, reaching the requested bound, and an
explicit clean stop finalize a capture. Abort, failure, or exhausted capacity
preserve incomplete recovery evidence, without publishing success. An explicitly
requested salvage operation may finalize verified fragments and record the
termination reason; it must not pretend the intended duration completed.

For callback audio, copy borrowed samples into a preallocated bounded queue
before returning. Do no filesystem writes or encoding in a real-time callback,
and never retain the array or a view. On queue overflow record a gap/status or
fail according to an explicitly selected capture policy; never silently drop.
For client-buffer audio, encode/consume the valid rows before reuse or transfer
ownership of a buffer from a bounded pool. The provider must not retain it.
Close providers using the existing protocol, including callback quiescence.

Each session gets an immutable capture ID even if its objects deduplicate with
another session. Record native frame spans, resolved media facts, source key,
requested/observed extent, timing and discontinuities, adapter/encoder versions,
and the actual termination reason. Reuse uFor recording fragments and gaps for
audio export instead of creating a competing timeline. Borrowed sample storage
is never part of a persistent manifest.

A caller may keep an unnamed capture under retention rules or assign a reference.
References protect their current targets. Moving `rehearsal/intro` to a new
capture atomically releases only that reference's old protection; pin the old
capture or give it another name to preserve it. Pinning a reference means pinning
its current target by immutable ID, so later movement cannot retarget the pin.
Reference removal is explicit. IDs are stable versions; automatic playback never
selects "latest" or substitutes a capture for a live source.

Replay selects a capture ID/reference through the host and obtains finite assets
or a recording definition. Export writes a portable score/package with normal
relative locations and content identities. Source grouping for newest-N policies
excludes session ID and capture bounds, but includes source and media context.

## Retention policy format

Separate three questions: is a result valid, is deletion forbidden, and when is
it normally worth discarding? HTTP freshness and deterministic validity answer
the first. Roots and `protect` answer the second. `retain` answers the third.

Roots are mandatory: references, unexpired pins, active leases, and dependencies
of protected manifests survive collection. Rules cannot override them. Rules are
unordered and additive; display order is only for explanation. Custom policies
replace the default rules, never the root invariants. Invalid policy fails before
any collection; do not silently fall back to a more destructive policy.

```toml
[cache]
policy_version = 1
maximum_object_bytes = "200 GiB"
maximum_staging_bytes = "20 GiB"
maximum_transport_bytes = "20 GiB"
minimum_free_space = "10 GiB"

[[cache.rules]]
name = "recent finite acquisitions"
match = { category = ["acquired", "generated"] }
retain = { duration = "30 days", since = "access" }

[[cache.rules]]
name = "fresh URL responses"
match = { source_kind = "download" }
retain = "while_fresh"

[[cache.rules]]
name = "recent sessions"
match = { category = "capture" }
retain = { duration = "7 days", since = "created" }

[[cache.rules]]
name = "latest three sessions per source"
match = { category = "capture" }
newest = { count = 3, group_by = "source" }
retain = "forever"

[[cache.rules]]
name = "short-lived derivatives"
match = { category = "derived" }
retain = { duration = "1 days", since = "access" }
```

This is the complete default rule set; capacities shown are example host settings
and must be chosen for the installation. Imports belong to `acquired` but default
to a permanent pin when explicitly saved; captures default to a reference when
named. Users can deliberately remove those roots to let the rules collect them.

Each rule requires a unique `name`, a nonempty `match` or `all = true`, and exactly
one of `protect` or `retain`. Both accept `"forever"`, `"while_fresh"`, or a duration
table. `protect` forbids pressure eviction; `retain` postpones ordinary collection
but permits pressure eviction. Only `source_kind = "download"` may use
`while_fresh`; an absent freshness deadline grants no protection/retention.

Selectors are limited to `category` (`acquired`, `generated`, `capture`, `derived`),
`source_kind`, provider `delivery`, `media_kind` (`audio`, `midi`, `image`, `other`),
`source_key`, and host-assigned `tags`. Fields combine with AND; a list is OR within
one field. Tags match when at least one supplied tag is present. Missing metadata
does not match. Origin-specific policy uses a host-assigned tag; avoid embedding
secret URLs in configuration. Names/references and pins need no matching rule
because they are already roots.

Durations use positive integer `seconds`, `minutes`, `hours`, or `days` (24 hours);
`since` is `created` or `access`. Size strings use positive integer `B`, `KiB`,
`MiB`, or `GiB`. All dates are UTC. Access means successful payload consumption,
not listing, explaining, scanning, or revalidation; initialize access at creation.

Optional `newest` selects up to N records after matching, grouped by source key
(`source`) or all matches (`all`), ordered by creation time then immutable ID.
Its count is a positive integer. Duration and newest constraints within one rule
both apply. Separate rules combine by union: the default keeps every capture for
seven days OR the latest three per source indefinitely, subject to pressure.
Changing policies or removing newer versions recomputes rank on surviving records.

No rule means an unrooted record is eligible at the next ordinary collection.
Use this explicit rule to keep selected deterministic outputs indefinitely:

```toml
[[cache.rules]]
name = "permanent generated values"
match = { category = "generated", tags = ["keep-generated"] }
protect = "forever"
```

Reject unknown fields, duplicate names, invalid enums/units, incompatible selectors,
and ambiguous combinations. `explain` reports matching rules, roots, ranks,
deadlines, and whether pressure can override retention. Removing a reference or
pin does not force deletion when another rule or root still protects it.

## Collection, capacity, and concurrent use

Ordinary collection selects records with no root, active protection, or active
retention. Pressure collection may additionally select retained records, but
never protected/rooted ones. Evict derived records first, then least recently
consumed records, then creation time and immutable ID for deterministic ties.
A selected capture releases its dependencies only when no other record/root needs
them. Count shared objects once; report logical sizes and incremental reclaimable
bytes separately. Keeping an object does not automatically keep all entries that
mention it.

Collection runs alongside playback and recording. Under the metadata lock,
recheck candidates and roots before unlinking metadata, then reclaim unreachable
objects. Active leases protect only their own dependencies. A dry run is an
explanation at a particular snapshot, not authorization to delete those same IDs
later without rechecking.

Reserve capacity before admission and extend reservations for bounded incoming
data. Account for staging and transport use as well as durable objects, metadata,
and recovery evidence when enforcing free space. Deduplication reduces durable
usage only after verification. Keep a conservative free-space margin because
other processes can consume disk space. If protected data prevents admission,
return a capacity error with required bytes and blocking roots. Never silently
unpin, overwrite a capture, or evict protected bytes.

Crash recovery and GC use the same reachability rules. Report incomplete material
separately with its size and recovery action; do not let it accumulate invisibly.
Expiration grants permission to delete; it is not a promise of backup or a legal
retention guarantee. Unnamed unpinned captures are deliberately evictable.

## Host operations

Implement library operations first:

- Resolve a finite declared asset by verified identity; fetch on authorized miss.
- Import local bytes or a current URL as a new finite entry.
- Materialize a provider or capture a bounded session.
- Open a specific entry/capture with a lease; export a finite package.
- Create/move/remove references and add/remove pins.
- List and explain without fetching, running providers, or refreshing access.
- Plan collection, apply collection with root rechecks, and inspect recovery.

These are host API responsibilities, not Python signatures fixed by this plan.
Acquisition honors the existing location allowlists and credentials policy;
cache lookup cannot grant new source execution authority. Failures distinguish
miss, denied acquisition, identity mismatch, corruption, incomplete capture,
provider contract violation, and insufficient capacity.

## Implementation stages and acceptance

1. **Policy evaluator and finite store.** Build manifest models, key fixtures,
   pure rule evaluation, object verification, leases, roots, atomic publication,
   and explain/dry-run. Cover all eight source kinds in metadata fixtures before
   adding I/O adapters. Demonstrate same-size corruption detection and one object
   shared by multiple entries without deleting it when just one expires.
2. **Local imports and remote acquisition.** Implement verified copy, HTTP and Git
   adapters outside uFor. Test missing HTTP expiry, response variants, `no-store`,
   conditional validation, and pinned offline reuse separately. A wrong download
   cannot replace a valid entry. Tests use controlled fixtures, not live servers.
3. **Materialization and capture.** Implement deterministic contracts, reusable
   buffers, finite capture/export, and explicit version selection. Test dependency
   and encoding changes in value keys, reused callback memory, queue overflow,
   clean stop versus abort, and partial-recovery diagnostics. Audio regression
   artifacts use 48 kHz and at least one second, per repository conventions.
4. **Collection and recovery.** Test the same evaluator under ordinary and pressure
   modes, latest-N plus age union, references moved between versions, expiring
   pins, shared objects, readers racing GC, writer interruption, and admission
   failure when everything is protected. All deletion decisions are explainable.

Do not postpone protection and capacity enforcement until after a working cache
has started accepting persistent data. Choose the actual host package during
implementation; no new fingerprint helper or runtime dependency belongs in uFor
merely because this plan uses one.

## Additional work beyond the prompt

None. This revision changes the plan only; it does not implement acquisition,
change the score format, select a host repository, or add dependencies.
