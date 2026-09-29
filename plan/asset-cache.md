# Asset cache: remaining host work

The verified finite-byte store, basic retention and collection, and bounded
capture sessions exist in `reccy/runtime/assets.py` and
`reccy/runtime/capture.py`. This plan covers acquisition adapters, provider
materialization, richer retention, capacity, recovery, and portable export.
The cache is a host facility; no uFor score field or cache API is needed.

The same object store can hold audio, MIDI, images, SysEx, captions, and
other finite bytes. Source location and media type do not change byte
identity. Private cache IDs and references must never become portable
score identities. Existing uFor locations and content identities are
described in [validation](../doc/validation.md); remaining host resolution
is tracked in [asset locations](url-paths.md).

## Source identity and authorization

Add a versioned canonical source/request fingerprint that includes the
location, resolved context, expected content identity, and relevant
representation settings. Relative paths need package identity; volume
paths need volume ID; Python requests need resolved rate and ordered
channels. Test null, booleans, integer versus float arguments, Unicode,
and dictionary ordering. Do not normalize URLs or provider values in ways
that change meaning.

Partition acquisition metadata by host credential scope. A matching hash
must not grant access to another scope. Do not store raw credentials,
cookies, signed URLs, or secret arguments in ordinary metadata. Use a
keyed local fingerprint when a secret affects lookup, and resolve the
actual value through host configuration. A redacted URL is for display,
not lookup.

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

## Provider materialization and capture integration

A trusted host registration may declare a finite buffer provider
deterministic under the value-key contract above. Nondeterministic output
is a new explicit materialization on each call. For arrays, specify a
lossless representation preserving dtype, shape, sample values, rate, and
channel order. Quantization, resampling, and lossy encoding create
separately identified derivatives. Thumbnails, waveforms, and indexes
can use the same object store with keys containing source identities and
transform settings/version.

Connect streaming URL, callback, and client-buffer adapters to the
existing bounded `CaptureSession`. Copy borrowed callback samples before
returning; do no filesystem I/O in the callback. For client-owned buffers,
consume valid rows before reuse. Preserve timing, discontinuities, gaps,
media facts, and actual termination reasons. Close providers according to
their protocol on clean stop, cancellation, and failure. Select a capture
by explicit ID or reference; never silently substitute the latest version
for a live source.

Export a selected capture as a finite portable score and package with
ordinary relative asset locations and verified content identities. Use
uFor recording fragments and gaps rather than another timeline model.

## Retention extensions

The current store supports references, pins, leases, duration/forever
rules, and ordinary/pressure collection for finite entries. Extend its
policy to support response freshness (`while_fresh`), capture versions,
derived objects, and a `newest` count per source or across all matches.
A rule is additive; separate rules combine by union. A newest count and
duration on one rule both apply. For example, retain captures younger
than seven days OR the latest three per source, subject to pressure.
Recompute rank when policy changes or versions are removed.

Proposed extension syntax, after capture records and freshness state exist:

```toml
[[cache.rules]]
name = "recent captures"
match = { category = "capture" }
retain = { duration = "7 days", since = "created" }

[[cache.rules]]
name = "latest three captures per source"
match = { category = "capture" }
newest = { count = 3, group_by = "source" }
retain = "forever"

[[cache.rules]]
name = "fresh downloads"
match = { source_kind = "download" }
retain = "while_fresh"
```

HTTP freshness determines whether a response can answer a current-URL
request. It does not determine whether verified bytes still exist, nor
does it override explicit roots or a `no-store` response. Only download
entries may use `while_fresh`; missing freshness grants no retention.
Keep custom policies explicit and reject invalid or ambiguous rules before
collection. Explain matching rules, roots, ranks, deadlines, and whether
pressure may override retention. Captures are evictable when unnamed and
unpinned; imports explicitly saved by a user should receive a durable root.

## Capacity and recovery

Enforce installation-specific maximum object, staging, and transport
bytes plus a minimum free-space margin. Reserve before admission and
extend reservations as bounded input arrives. Account for incomplete
staging and recovery evidence, not just published objects. If protected
data blocks admission, report required bytes and blocking roots; never
silently unpin or overwrite a capture.
The proposed policy keys are `maximum_object_bytes`,
`maximum_staging_bytes`, `maximum_transport_bytes`, and
`minimum_free_space`; size values use positive integer `B`, `KiB`, `MiB`, or
`GiB` units.

Complete crash recovery for dead process leases, incomplete sessions,
staged files, and orphaned objects. Do not reclaim a live lease based only
on elapsed time. A dry run must explain proposed recovery; collection
must recheck roots under the metadata lock before deletion. Report
incomplete material with its size and available recovery action.

## Remaining operations and acceptance

1. Implement local/volume verified copy and policy-gated HTTP and Git
   acquisition. Test missing HTTP expiry, variants, `no-store`, conditional
   validation, pinned offline reuse, redirects, identity mismatches, and
   interrupted transfers with controlled local fixtures.
2. Implement deterministic materialization, derivative identity, provider
   adapters, and portable capture export. Test dependency and encoder
   changes in value keys, callback buffer reuse, client-buffer short reads,
   clean stop, abort, salvage, and partial-recovery diagnostics.
3. Extend policy and collection to freshness, newest-N, capture and
   derivative dependencies, capacity pressure, and recovery. Test shared
   objects, moved references, expiring pins, readers racing collection,
   writer interruption, and admission failure when all space is protected.
4. Expose host operations to resolve, import, materialize, capture, open,
   export, explain, and inspect recovery. Keep acquisition authority in
   the host and distinguish a miss, denied acquisition, wrong identity,
   corruption, incomplete capture, provider error, and insufficient space.

Tests use local fixtures, not public services. Audio regression artifacts
use 48 kHz and at least one second where audio output is compared.

## Additional work beyond the prompt

None.
