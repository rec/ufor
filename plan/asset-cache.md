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

Reccy now provides a versioned source/request fingerprint and partitions its
verified store by a required host-issued credential scope. The fingerprint
covers public location, resolved context, expected content identity, and
representation settings; a host-private key can fingerprint lookup secrets
without persisting them. Reccy rejects raw source descriptions as store keys.

Acquisition adapters still need to supply complete effective facts: relative
paths need package identity, volume paths need volume ID, and Python requests
need resolved rate and ordered channels. Hosts must resolve actual credentials
through their own configuration and authorize every acquisition independently
of the fingerprint. Do not put raw credentials, cookies, signed URLs, or secret
arguments in ordinary metadata. A redacted URL is for display, not lookup.

## Behavior for every source

| Source | Automatic behavior | Explicit storage |
| --- | --- | --- |
| Relative file | Read and verify in place when the host trusts it to remain immutable; otherwise use a snapshot | Import an independent byte snapshot |
| Volume file | Resolve approved volume; use a direct read only for trusted immutable files | Import an independent byte snapshot |
| Download URL | Acquire and verify finite bytes; store if response policy permits | Retain or pin the resulting entry |
| Git file | Acquire commit/path-selected blob and verify content | Retain or pin the resulting entry |
| Streaming URL | Open a new live session; no automatic recording | Capture a bounded realization |
| Python buffer | Evaluate each time unless a deterministic contract is configured | Materialize finite output |
| Python callback | Open a new session; borrowed arrays | Capture through bounded client-owned buffers |
| Python client buffer | Open a new session; reuse client storage | Capture before reusing filled storage |

Reccy now provides bounded stream admission, confined relative file snapshots,
and verified direct reads through one open handle. Its file helper rejects
traversal, symlinks, and nonregular files. Hosts still choose trusted immutable
direct reads versus snapshots and map approved volume IDs to roots. Direct
reads create no payload entry, and GC must never delete external files. An
import copies bytes, not a mutable hard link or symlink. A direct read is sound
only while the host can trust that another process will not change the open
file's contents after verification.
Recs now has an explicit finite-asset resolver in
`recs/recording/asset_resolver.py`. It requires a scoped store, measured volume
mounts, approved remote URLs, Git transport storage, and byte/time limits from
the host. Offline edit preparation uses that resolver for selected recording
fragments and holds cache leases through rendering. Ordinary `recs edit`
commands accept an explicit operator-owned asset policy file with measured
volume IDs, approved URLs, and cache settings. `recs session export` accepts
the same policy and rewrites verified finite assets to relative files in a
portable package. Composition, calibration, and recording playback still use
session-relative files.

The existing Python provider protocol remains audio-specific. Other finite asset
types need no provider protocol change to be cached. Future typed generators can
supply bytes to the same store; this plan does not invent image/MIDI ndarray or
stream interfaces.

## HTTP: response freshness versus retained content

There are two distinct operations:

- Resolving an existing uFor asset requests its expected SHA-256 and length.
  Reccy's scoped `open_expected()` now leases and verifies a matching retained
  object even if the acquisition URL has changed or become unavailable. The
  host must authorize the request before that lookup.
- Fetching a URL's current representation uses HTTP response caching rules. Its
  freshness says when a response can answer that request without validation.
  Changed bytes are a new acquisition, never an automatic score update.

HTTP expiration does not corrupt stored bytes or require their deletion. Retention
is a separate policy. A mutable URL lookup without a known hash is a host import
operation; current finite uFor assets still require `content`.

Reccy now resolves known-hash HTTPS assets from the scoped store or acquires a
bounded, verified response under host URL policy. Its immutable asset adapter
handles gzip content decoding, redirect reauthorization, and transient
`no-store` responses. Its current-URL import now keeps scoped response
metadata, calculates RFC 9111 explicit freshness and corrected age, and
validates stale responses with ETag or Last-Modified. It serializes updates
per request key and conservatively keys every request header to avoid `Vary`
collisions. Host-level integration with score imports remains to be done.

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

Reccy now imports a full-commit, path-selected regular blob from a host-approved
local Git object store, returning the observed blob ID separately from the
verified file identity. Its remote adapter fetches the pinned commit with a
blob filter, then fetches the selected blob; if a server refuses a direct blob
request, it can fetch the commit without a filter. The host must authorize the
repository URL and provide a bare Git object store on quota-limited storage.
Consuming-host integration and transport-store GC remain.

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
Reccy now provides deterministic finite-byte value caching keyed by a
host-supplied source fingerprint. It remembers the first content identity
across collection and invalidates the mapping on conflicting regeneration.
Provider invocation, effective-argument resolution, and audio encoding still
belong to the consuming host.

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
Reccy now offers atomic export of one verified finite entry to a host-approved
destination. Recs can assemble a portable recording package from verified
relative, volume, HTTPS, and Git assets, rewriting non-relative locations to
relative files. Captured streaming realizations still need a host path from
the capture result into a sealed recording score before this export can use them.

## Retention extensions

The current store supports references, pins, leases, duration/forever
rules, newest-N per source or across all matches, download-only response
freshness (`while_fresh`), and ordinary/pressure collection for finite entries.
Collection now removes expired asset-pin metadata along with eligible entries.
`CaptureStore` now applies additive duration, newest, forever, and protection
rules to completed captures and recovery evidence. Named capture references,
capture pins, and active record leases are roots; ordinary and pressure
collection release fragment pins only after all surviving records stop using
them. A subsequent `AssetStore.collect` reclaims eligible entry bytes. Recovery
evidence expires automatically under these rules. Derived-object dependencies
still need policy integration.
A rule is additive; separate rules combine by union. A newest count and
duration on one rule both apply. For example, retain captures younger
than seven days OR the latest three per source, subject to pressure.
Recompute rank when policy changes or versions are removed.

Proposed host configuration syntax, after the policy is wired into a host:

```toml
[[cache.rules]]
name = "recent captures"
match = { category = "capture" }
retain = { duration = "7 days", since = "created" }

[[cache.rules]]
name = "latest three captures per source"
match = { category = "capture" }
newest = { count = 3, group_by = "source" }

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
Reccy now optionally enforces object, staging, and free-space budgets for
asset admissions with serialized writers and incremental staging checks.
Cooperating processes must use the same capacity. Remote Git acquisition now
requires host-provided quota-limited transport storage; automated provisioning
and GC for that storage, pressure collection, capture reservations, and
blocking-root explanations remain.
Recs now requires object, staging, and free-space budgets in its explicit
offline edit and package-export asset policy. Its Git transport repository
still requires an external hard quota.
The proposed policy keys are `maximum_object_bytes`,
`maximum_staging_bytes`, `maximum_transport_bytes`, and
`minimum_free_space`; size values use positive integer `B`, `KiB`, `MiB`, or
`GiB` units.

Complete crash recovery for dead process leases, incomplete sessions,
staged files, and orphaned objects. Do not reclaim a live lease based only
on elapsed time. A dry run must explain proposed recovery; collection
must recheck roots under the metadata lock before deletion. Report
incomplete material with its size and available recovery action.
Reccy now has read-only inspection of staging files and unreferenced objects,
including sizes. It cannot yet distinguish an active staging writer from an
abandoned one or reclaim recovery material safely.

## Remaining operations and acceptance

1. Connect host-owned local/volume root authorization and remote Git acquisition
   to the existing verified admission. Reccy now has a generic volume-ID
   resolver, direct-read/snapshot file adapter, and remote Git fetch adapter;
   recs has a policy-injected finite-byte resolver and ordinary offline edit
   commands hold its leases during decoding. Their policy files supply measured
   mounts and require operator-provided quota-limited Git transport storage.
   Recs package export also accepts this policy and rewrites finite assets;
   other recs consumers still need this integration.
   Integrate current-URL HTTP imports in hosts. Test missing
   HTTP expiry, variants, conditional
   validation, pinned offline reuse, redirects, identity mismatches, and
   interrupted transfers with controlled local fixtures.
2. Implement deterministic materialization, derivative identity, provider
   adapters, and portable capture export. Test dependency and encoder
   changes in value keys, callback buffer reuse, client-buffer short reads,
   clean stop, abort, salvage, and partial-recovery diagnostics.
3. Extend policy and collection to derivative dependencies, capacity pressure,
   and crash recovery. Test writer interruption and admission failure when all
   space is protected. Capture and recovery record
   retention, shared salvage fragments, moved references, active reader leases,
   and root rechecks are implemented.
4. Expose host operations to resolve, import, materialize, capture, open,
   export, explain, and inspect recovery. Keep acquisition authority in
   the host and distinguish a miss, denied acquisition, wrong identity,
   corruption, incomplete capture, provider error, and insufficient space.

Tests use local fixtures, not public services. Audio regression artifacts
use 48 kHz and at least one second where audio output is compared.

## Additional work beyond the prompt

None.
