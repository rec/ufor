# Asset locations: remaining host work

The version 4 location models, validation, schema, conformance data, and
migration are implemented in uFor. See [validation](../doc/validation.md)
and [the asset cache plan](asset-cache.md) for the current contract and
storage work. This plan now covers host resolution, acquisition, providers,
and consumer capability checks. uFor does not perform I/O or import NumPy.

## Relative files

`RelativeFileLocation` preserves the current rules. Its POSIX path resolves from
the directory containing the score. Reject absolute POSIX paths, Windows drives,
URLs, backslashes, `.` as the complete path, and any `..` component. Symlink
handling belongs to the host. Reccy's current confined-file helper rejects
symlinks entirely; another host strategy must prove that resolution stays
inside the package root. A direct verified read is permitted only when the
host trusts the file to remain immutable during use. Mutable files need a
verified snapshot.

```toml
[[assets]]
name = "local-take"
encoding = "WAV/PCM_24"
content = { byte_length = 576044, sha256 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef" }
location = { kind = "relative_file", path = "audio/take.wav" }
```

## Files on a volume

A volume location identifies the volume and a path below its root. Never save a
machine-specific mount path such as `/Volumes/Archive` or `D:\\Archive`.

`volume_id` is an opaque stable identifier supplied by the host, preferably the
filesystem/volume UUID. `volume_name` is optional human-facing evidence for UI
and diagnostics; it is not used as identity. `path` is a relative POSIX path
with the same traversal rules as a relative file.

```toml
[assets.location]
kind = "volume_file"
volume_id = "e44a2ec7-54d2-4b35-88e4-582d978c4e44"
volume_name = "Field Recordings"
path = "2026/forest/take-03.wav"
```

The host maps `volume_id` to a currently mounted root. Missing, duplicated, or
mismatched volumes are resolution errors. A matching display name must never
silently substitute for a missing ID. Export can copy the content into the score
package and rewrite the location to `relative_file`.
Reccy now provides a resolver for host-measured volume IDs and a file adapter
that reads trusted immutable bytes directly or snapshots mutable bytes. A
display-name change does not invalidate a stable ID. Consuming hosts still
have to populate the measured mount registry and authorize roots. Recs now has
an explicit finite-byte resolver that accepts those measured mounts. Ordinary
offline edit commands can supply an operator-owned policy file and hold leases
through rendering. Recs package export accepts the same policy and rewrites
verified volume assets as relative files; recording playback still uses
session-relative files.

## Download URLs

`DownloadLocation.url` is an absolute URI for one finite byte object. Initially
support `https`; add other schemes only with an explicit host adapter. Fragments
are forbidden because they are not sent in retrieval requests. Redirects are
allowed only under host policy, and the final bytes must match `content`.

```toml
[assets.location]
kind = "download"
url = "https://media.example.org/sessions/take-03.flac"
```

The score stores no cookies, authorization headers, signed-request secrets, or
credentials. Hosts associate credentials and network policy with an origin or
adapter outside the score. Query strings are permitted because some object names
need them, but authors should not put expiring signatures or secrets in portable
scores.

Retrieval is complete before a download asset becomes usable. Cache keys use the
declared SHA-256, not the URL. Offline use succeeds from a verified cache even if
the URL is unavailable. A hash mismatch is an error, never an automatic metadata
update.

Reccy's immutable HTTPS adapter implements this known-hash path with bounded
transfer and decoded-body sizes, host-authorized redirects, and transient
handling for `no-store` responses. Hosts still supply credential and URL policy.

## Git files

Git locations separate repository transport from the selected object:

```toml
[assets.location]
kind = "git_file"
repository = "git://git.example.org/sounds/library.git"
commit = "8d9f6f05f451f5fa204c2d0f10f67f00365e93ac"
path = "impulses/hall.wav"
```

Allow repository URLs accepted by the configured Git host, including `git://`,
`https://`, `ssh://`, and `git+...` adapter forms. Do not accept scp shorthand
such as `host:path`, whose URI and local-path interpretation is ambiguous.

`commit` is a full object ID, never a branch, tag, abbreviated hash, or symbolic
revision. `path` is a relative POSIX repository path without `.` or `..` and must
select a regular blob, not a submodule, tree, symlink escape, or Git LFS pointer
unless the host explicitly resolves and verifies the LFS object. Retrieved bytes
must also match the asset's SHA-256. The commit identifies repository history;
the SHA-256 identifies the actual asset bytes across source kinds.

Ufor does not run Git. Reccy has local-object and remote-fetch adapters. The
remote adapter requires a host-approved repository URL and a bare object store
on quota-limited transport storage; it does not create a working tree.
Credentials, known-host policy, executable selection, transport-store GC, and
consumer integration remain host responsibilities.

## Streaming URLs

A streaming location declares a media session rather than a sealed file:

```toml
[assets.location]
kind = "stream"
url = "https://radio.example.org/live/main.m3u8"
transport = "hls"
```

The URL syntax alone does not determine delivery semantics. For example, HTTPS
can carry a complete file, progressive audio, HLS, DASH, or an Icecast response.
`transport` names the host adapter and may initially include `http_progressive`,
`hls`, `dash`, `icecast`, `rtsp`, and `srt`. The vocabulary is extensible through
host capabilities; Ufor validates only identifier spelling and the absolute URI.

A streaming audio description declares its native rate/timebase and channel
layout but normally omits `frames` and `content`. The stream begins when a host
opens it. The score does not imply that two openings yield the same samples.

Hosts report capabilities before composition:

- whether seeking is supported and over what window;
- whether the extent is currently known;
- startup/buffering latency;
- whether timestamps are supplied by the source or synthesized by the host;
- whether reconnection creates one logical stream or a discontinuity;
- whether the declared rate and channels match the opened stream.

Do not hide reconnect, dropout, or format-change behavior in Ufor. A recorder
turns received samples and discontinuities into an ordinary recording score with
finite assets, fragments, clock observations, and explicit gaps. Offline
rendering rejects an unrecorded live stream unless the host provides a previously
captured realization.

## Python buffer providers

A trusted provider location names an importable function; it does not contain
Python code:

```toml
[assets.location]
kind = "python_provider"
module = "show_audio.generators"
function = "opening_tone"
delivery = "buffer"
arguments = { frequency_hz = 440.0, duration_seconds = 2.0 }
```

The host resolves the module through its configured Python environment and calls:

```python
def opening_tone(request: AudioProviderRequest) -> numpy.ndarray: ...
```

`AudioProviderRequest` contains the validated JSON arguments, declared sample
rate, ordered channel names, and required frame count. The function returns one
C-contiguous NumPy array with shape `(frames, channels)`. The canonical sample
representation is floating point with finite values in `[-1, 1]`; initially
accept `float32` and `float64`, with the host converting to its engine format.
Reject rank-one mono arrays, channel-first arrays, object arrays, integer arrays,
nonfinite values, incorrect frames/channels, and mutation of the request.

Ufor core does not import NumPy or the provider. Put the request protocol and
array validation in a host/provider package. Ufor validates only the declaration
and its finite audio description.

Provider loading executes trusted local code and is never enabled merely because
a TOML document contains this location. The host must opt into Python providers
and restrict modules according to its plugin/library policy. Import failures and
provider exceptions become preparation diagnostics with the asset name and
provider reference; do not catch user interruption or retry automatically.

## Python callback streaming providers

Use `delivery = "callback"` for a live source that owns its input buffers and
decides when audio is available:

```toml
[assets.location]
kind = "python_provider"
module = "show_audio.inputs"
function = "stage_feed"
delivery = "callback"
arguments = { device = "stage-left" }
```

The named function constructs one stateful stream:

```python
class AudioBlockCallback(Protocol):
    def __call__(
        self,
        samples: numpy.ndarray,
        timing: AudioBlockTiming,
        status: AudioBlockStatus,
    ) -> None: ...


class CallbackStream(Protocol):
    def run(self, consume: AudioBlockCallback) -> None: ...
    def close(self) -> None: ...


def stage_feed(request: AudioProviderRequest) -> CallbackStream: ...
```

`AudioBlockCallback` receives a borrowed C-contiguous `(frames, channels)`
`float32` or `float64` array with at least one frame, plus source timing and
status observations. The provider owns the array and may overwrite or reuse its
memory as soon as the callback returns. The callback must not mutate the array,
retain it or a view of it, or pass either to another thread. It copies samples
into client-owned storage during the call when it needs a longer lifetime.
This borrowed lifetime intentionally matches sounddevice and PortAudio callback
buffers, whose storage may be reused for later calls.

Callback calls are serialized and never overlap. Chunk sizes may vary and do
not change the timeline; concatenating the blocks in callback order defines the
sample stream. Timing observations preserve source timestamps when available.
Status observations report overflow, dropped frames, discontinuities, and other
source conditions rather than silently treating them as contiguous audio. The
host/provider package defines these observation types without adding NumPy to
Ufor core.

`run()` performs delivery until clean end of stream, cancellation, or failure.
Returning means clean completion and raising means failure. The host arranges
the execution context required by the provider. It calls `close()` exactly once
on completion, cancellation, or error, and `close()` does not return while a
callback can still be running. The callback must not call `close()` itself. A
real-time provider may impose a callback deadline; callback delivery provides no
backpressure, so missed deadlines are reported as stream status or failure.

For finite declared `frames`, callbacks must deliver exactly that many frames.
With `frames = null`, the stream may be open-ended. Seeking and replay are
unsupported unless a future provider protocol declares them explicitly.
Offline rendering rejects an open-ended callback stream rather than waiting for
it to finish.

## Python client-buffer streaming providers

Use `delivery = "client_buffer"` when the consumer must control allocation and
reuse its own storage:

```toml
[assets.location]
kind = "python_provider"
module = "show_audio.generators"
function = "generated_feed"
delivery = "client_buffer"
arguments = { frequency_hz = 440.0 }
```

The named function constructs one stateful stream:

```python
class ClientBufferStream(Protocol):
    def read_into(self, destination: numpy.ndarray) -> int: ...
    def close(self) -> None: ...


def generated_feed(request: AudioProviderRequest) -> ClientBufferStream: ...
```

The client allocates a writable, C-contiguous `(capacity_frames, channels)`
`float32` or `float64` array and may pass that same array to every `read_into`
call. The provider writes the first `frame_count` rows and returns that count.
A positive result must not exceed `capacity_frames`; a short read is valid, and
zero means clean end of stream. Boolean, negative, and oversized results are
errors. The provider must not retain `destination` or any view of it after the
call returns. Rows after `frame_count` remain client-owned and have no defined
new value.

Calls are synchronous and serialized. `read_into` waits until it can return at
least one frame, reaches the end, or raises an error; zero never means
temporarily unavailable. The client calls `close()` exactly once on normal
completion, cancellation, or error. Finite frame declarations, lack of seeking,
and offline-render restrictions match the callback stream contract.

This API removes the required per-chunk array allocation. It does not promise
that provider internals allocate nothing, but it lets a real-time host use a
preallocated pool or ring buffer and require allocation-free provider
implementations as host policy. Buffer capacity is chosen by the client from
its engine constraints and is not part of the Ufor document.

## Resolution API and capabilities

Keep location parsing separate from realization. Introduce pure validation in
`ufor.assets` and host-owned resolvers selected by location kind:

```python
class ResolvedAsset(Protocol):
    audio: AudioDescription
    seekable: bool


class FiniteAudio(ResolvedAsset, Protocol):
    def read(self, start_frame: int, frame_count: int) -> AudioBlock: ...


class CallbackStreamingAudio(ResolvedAsset, Protocol):
    def run(self, consume: AudioBlockCallback) -> None: ...


class ClientBufferStreamingAudio(ResolvedAsset, Protocol):
    def read_into(self, destination: AudioBlock) -> int: ...
```

These are illustrative host protocols, not Pydantic document models. Callback
blocks are provider-owned borrows; client-buffer blocks are client-owned writable
storage. Ufor functions receive declared and verified facts; they do not acquire
resources.

The resolver must return observed facts and compare them to the declaration
before use:

- encoding or stream transport;
- native rate and ordered channel layout;
- finite frame count when declared;
- byte length and SHA-256 for encoded finite content;
- seekability and known extent;
- source timestamps/discontinuities for streams.

A mismatch is a preparation error. Never silently rewrite the score, resample,
remap channels, truncate, pad, or select a different volume/revision. Explicit
import or capture tools may create a new definition from observed facts.

## Composition and playback rules

Location does not change the logical meaning of slices, clips, routes, or audio
streams. Those models continue to use native integer frames and named channels.
The source's capabilities determine whether a requested operation is realizable.

- A sample slice requires finite, seekable audio because it can start at an
  arbitrary frame, loop, reverse, or retrigger.
- An arrangement clip with a nonzero source start requires seeking or a captured
  finite realization.
- Reverse and mirror playback require finite random access.
- A live stream may feed a forward-only live input from its opening point.
- Reusing one streaming asset in two parts does not imply shared consumption.
  The host must either open two independent sessions or explicitly provide a
  shared fan-out source with one timeline.
- Deterministic/offline composition rejects unresolved live URL and streaming
  provider locations.
- Recording any stream produces finite file assets; the resulting recording
  does not retain the live locator as its audio payload identity, though it may
  preserve it as provenance in a later provenance model.

Validate capability requirements during host preparation, after resolution but
before starting output. Static Ufor validation rejects operations that are
inherently incompatible with a declared streaming kind when that can be known
without I/O.

## Security and trust boundary

Every non-relative location expands authority and must be opt-in host policy:

| Location | Authority exercised by the host |
| --- | --- |
| Relative file | Read below an approved package root |
| Volume file | Read an approved mounted volume |
| Download | Make an outbound request and populate a cache |
| Git file | Contact/inspect a repository and read an object |
| Stream URL | Maintain a network session and decode unbounded input |
| Python provider | Import and execute local code |

Validation of a document does not grant any of these permissions. Provide a
resolution policy listing allowed kinds, URI schemes/origins, volume IDs,
repository origins, stream transports, and Python module prefixes. Default to
`relative_file` only for ordinary portable packages.

Resolvers must defend against path traversal, symlink escapes, redirect policy
violations, DNS/address rebinding according to host policy, decompression bombs,
oversized downloads/caches, Git submodule/LFS surprises, decoder resource limits,
and providers that deliver invalid or unbounded data. These are host concerns but
the resolver contract must surface precise errors rather than weakening them.

Scores never contain secrets. Logging and diagnostics may show an origin and
redacted path but must not reveal query credentials, local tokens, headers, or
provider argument values marked secret by host configuration.

## Interchange, copying, and sealing

Define two package states:

- A **resolved score** has declarations that a particular host can realize.
- A **sealed package** contains only finite content whose bytes are present or
  retrievable and verified by `ContentIdentity`.

Relative, volume, download, and Git assets can participate in a sealed package
after verification. A portable exporter copies their bytes below the package
root and rewrites each location to `relative_file`, preserving the content hash.
A buffer provider can be materialized by encoding its returned array into a file,
then recording the actual encoding, length, hash, timebase, channels, and frames.

Live URL, callback-provider, and client-buffer-provider locations cannot be
sealed directly. Capture a finite realization first. Do not label a score
sealed merely because its stream URL or provider declaration is stable.

TOML and JSON use the same discriminated location objects. JSON Schema describes
their structure; Python and other language implementations must additionally
enforce the cross-field source/facts matrix and URI/path rules.

## Remaining implementation stages

### 1. Local and volume host resolution

- Port the current relative-file resolution to the new model.
- Define the host volume registry and exact missing/ambiguous/mismatch errors.
- Verify encoded byte facts and decoded audio facts before publishing a handle.
- Recs package export now copies verified finite locations into relative files;
  other hosts still need their own export path.

Acceptance: moving the package preserves relative files; changing a mount point
preserves a volume asset; a same-named wrong volume is rejected; symlink escapes
and hash mismatches fail.

### 2. Downloads and Git

- Connect the verified cache to bounded download and Git acquisition.
- Add explicit download and Git resolver adapters under host policy.
- Resolve Git commits and blobs without checking out arbitrary working trees.
- Keep authentication outside score data.

Acceptance: cached offline replay is byte-identical; redirects and repository
aliases cannot bypass policy; moving a tag or branch is irrelevant because only
full commits are accepted; wrong bytes fail before decoding.

### 3. Streaming URLs

- Define transport-adapter capability reports and discontinuity observations.
- Permit only forward live-input use in the first implementation.
- Feed recording through the existing fragment/gap representation.
- Reject unsupported seek, reverse, loop, and offline requests before playback.

Acceptance: HLS-over-HTTPS is distinguishable from finite HTTPS download;
dropouts become explicit recording gaps; reconnect policy is visible; no live
stream is described as sealed or deterministic.

### 4. Python providers

- Define provider request types in the host/provider package.
- Implement opt-in module/function resolution and JSON arguments.
- Validate full arrays and every callback block at the boundary.
- Implement callback streams with provider-owned borrowed arrays, serialized
  delivery, timing/status observations, and cleanup on every exit path.
- Implement client-buffer streams with client-owned reusable arrays, strict
  returned-frame-count validation, and no retained destination references.
- Add a materialization command that converts buffer output to a sealed relative
  audio file.

Acceptance: wrong dtype/shape/channel/frame/nonfinite output fails with the asset
and provider named; callback blocks concatenate without losing or duplicating
frames; borrowed callback arrays are never retained; client-buffer providers can
repeatedly fill the same array without changing its identity; exceptions close
the provider once.

### 5. Consumer capability validation

- Validate these requirements against resolved handles before starting output.

Acceptance: every unsupported combination fails before output with the exact
asset and requested operation.

## Host integration tests

Use local fixtures for volume-root mapping, symlink escapes, a loopback
HTTP server, a local bare Git repository, and finite stream adapters. Test
provider functions that return arrays, invoke callbacks, and fill reusable
client buffers. Cover identity mismatches, denied origins and modules,
redirects, intermittent network failures, borrowed-buffer lifetime, short
reads, end-of-stream, callback status, provider cancellation, and cleanup.
Check unsupported seek, reverse, loop, and offline requests before output.
Network tests must not depend on public services. Where audio output is
compared, regression WAV fixtures use 48 kHz and at least one second.

## Additional work beyond the prompt

None.
