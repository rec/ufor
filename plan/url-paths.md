# Asset locations: remaining host work

uFor's structured location models and validation are described in
[validation](../doc/validation.md). This plan covers host acquisition, live
sources, Python providers, capability checks, and sealing that remain outside
the portable format library. The related storage work is in the
[asset cache plan](asset-cache.md).

## Project applicability audit

Reviewed the local checkouts on 2026-11-04. These are integration opportunities,
not claims that every project needs every location kind or has adopted reccy's
asset APIs. Direct beneficiaries are **enge, recs, safaz, streamO, and showCo**.
**arpeg** benefits through sample preparation in enge. **baccy, cntrl, lyte,
meedee, and tuney** have narrower or conditional uses described below.
**reccy** owns reusable infrastructure and **uFor** benefits from consistent host
implementations. No current acquisition requirement was found for **dvice,
enveLFO, nmr, or rec**.

| Project / checkout | Evidence and useful scope |
|---|---|
| arpeg | The README describes sample-region realization through enge. Verified prepared samples benefit this path; the event core and browser synth need no Python URL resolver. Live sample playback remains unwired. |
| baccy | `baccy/copy.py` snapshots and hashes local files, including actively growing recording logs. Reusable finite-file verification could help completed-file ingestion, but permanent backups, source stability, append-only log snapshots, and backup catalogue semantics must stay in baccy. An evictable cache cannot replace its backup store. |
| cntrl | `cntrl/catalogue.py` reads controller definitions; maker tools load graphics and firmware. Verified finite inputs could help an explicit downloaded setup/graphics workflow. Current local catalogue loading alone does not justify remote resolution, and device flashing stays outside this plan. |
| dvice | `dvice/discovery.py`, `poller.py`, and `supervision.py` supervise device discovery and processes. No media acquisition role; hosts resolve assets. |
| enge | `enge/sampler.py` prepares immutable decoded sample buffers. Its preparation callers need verified encoded bytes and decoded-fact checks before rendering; acquisition must remain outside the render loop. |
| enveLFO (`envelfo`) | `envelfo/runtime.py` and `patch.py` execute controls supplied by callers. No asset acquisition requirement in the control runtime. |
| lyte | `lyte/authoring.py` uses configured uFor libraries. Verified distribution of score libraries is a possible host integration; current procedural pixel/DMX rendering does not require audio-stream or image adapters. Importing downloaded Python declarations still requires explicit trust. |
| meedee | SMF, SYX, clip, and event-archive codecs accept file data (`meedee/smf.pyi`, `syx.pyi`, `archive.pyi`); `_ufor_cli.py` reads a local score. Hosts could acquire verified MIDI/event files before passing them to codecs. Native MIDI transport needs no URL handling. |
| nmr | `nmr/words.py` reads bundled or explicitly supplied word lists. Stable vocabulary matters, but there is no current remote vocabulary workflow requiring an asset resolver. |
| rec | The repository is a profile/resume/project dashboard, not a media runtime. No acquisition integration identified. |
| reccy | Owns generic finite-byte acquisition, leases, retention, capture storage, and reusable additions below. It must not depend on uFor, NumPy, media decoders, or host-specific score policy. |
| recs | `recs/recording/asset_resolver.py` already integrates finite locations for editing/export. Benefits from reusable preflight and package operations, plus the separately planned stream/provider adapters and capture lifecycle. |
| safaz | `safaz/reader.py` resolves SFZ sample dependencies; `safaz/assets.py` opens samples separately for metadata, hash, and loop inspection. Preparing one verified snapshot for all inspection would keep those facts tied to the same bytes. SFZ parsing and embedded-loop interpretation remain in safaz. |
| showCo (`showco`) | `showco/provision/media.py` deploys movie/photo inputs and configures streamO. Benefits from a verified media manifest and preflight before deployment, then verification at the destination. It delegates decoding and playback to streamO. |
| streamO (`streamo`) | `streamo/image_feed.py` downloads bounded JPEGs; its media pipeline consumes photos and movies through external tools. Reuse current-URL acquisition and credential scoping, then retain image validation and feed cursors locally. Outbound RTMPS/Icecast publishing is not an inbound stream asset. |
| tuney | `tuney/scale/scala_browser.py` loads a bundled ZIP of Scala definitions; `tuney/config/text_file.py` reads text. Explicit external tuning/preset/text imports could use finite-byte acquisition. No remote catalogue or new archive-location scheme is needed for the bundled resource. |
| uFor (`ufor`) | Owns portable locations, identities, media declarations and conformance cases. Keep its explicit local library loader separate from host acquisition and never add network access or provider execution to core models. |

## Existing reccy support and remaining shared additions

Use the current implementations, rather than recreating them:

- `runtime/assets.py` and `file_assets.py`: verified bounded finite-byte imports,
  volume-root matching, immutable direct handles, snapshot copies, reader leases,
  references/pins, retention, capacity limits, recovery, and single-entry export.
- `runtime/http_assets.py`, `http_current.py`, and `http_freshness.py`: known-hash
  HTTPS acquisition and separate mutable current-URL imports with freshness and
  conditional requests. streamO's feed image import is a consumer opportunity,
  not evidence that HTTP freshness is missing.
- `runtime/git_assets.py`: both local and remote pinned-commit blob acquisition.
  Hosts still provision and authorize the quota-limited transport repository.
- `runtime/value_assets.py` and `capture.py`: deterministic encoded-result
  caching and bounded fragment capture, including explicit gaps and recovery
  evidence. They do not execute Python audio providers or decode stream protocols.

The following additions are justified by the consumers above. Implement only
generic byte/lifetime operations in reccy; host integrations remain separate work.

### Asset-set preflight

For recs edits, safaz instruments, enge sample preparation, and showCo/streamO
media deployment, report every required asset's availability, authorization,
verified identity and preparation failure before output begins. Include explicit
offline/cache-only operation so a rehearsal or export can prove that no source
needs fetching. Distinguish a metadata-only inventory from completed byte
verification; checking existence is not a successful preflight.

Reccy already opens one authorized retained identity through `open_expected()`;
it lacks an asset-set preparation/report operation. A shared operation should
accept host-enumerated requests, preserve their diagnostic labels, and retain
leases or pins through the consuming operation. Each host enumerates score/SFZ
dependencies and validates decoded facts. Do not move uFor traversal into reccy
or grant access merely because bytes exist in a cache.

### Managed paths for external consumers

streamO's external media tools need paths, whereas reccy's verified read APIs
return leased streams. `object_path()` exposes a storage path but does not itself
verify or lease it; `export_entry()` makes a permanent single-file copy. Add a
context-managed verified path operation for tools that cannot consume the open
stream. It must protect the asset for the entire child-process lifetime and
clean up any temporary materialization after that child exits. Prefer existing
leased streams wherever the decoder accepts them. The host owns process
lifecycle and any filename/format requirements. Do not persist transient
`no-store` HTTP responses through this path.

### Verified multi-file packages

Extend single-entry export with a reusable finite-file manifest and staged
package publication for recs, safaz instrument dependencies, and showCo's
streamO media deployment. Deduplicate identical bytes where package semantics
permit, reject conflicting destination paths, verify every member, and publish
the package only after preparation succeeds. Destination verification must use
the manifest's identities, not source filenames or transfer success alone.
Failure must leave the previous usable package intact.

Reccy can own bounded copying, identity verification, and publication primitives;
hosts choose layout, enumerate dependencies, rewrite score/config references,
and perform remote transfer. baccy may consume a completed manifest but retains
its own permanent backup policy. This does not introduce a distributed
transaction, automatic directory synchronization, or an archive URI scheme.

Prioritize these finite-media integrations over new inbound HLS/DASH adapters:
the reviewed applications provide concrete finite-file consumers, while
streamO's outbound publishing is not evidence of demand for those adapters.
Keep the stream/provider contracts below as planned host work, not implemented
reccy features or requirements imposed on every project.

## Finite-location integration

Recs already resolves verified relative, volume, HTTPS download, and Git file
assets for offline editing and package export under an explicit operator policy.
Its other consumers and other hosts still need equivalent integration. They
must resolve relative paths beneath the package root, use a measured volume ID
rather than a display name or mount path, authorize remote origins, and compare
both encoded byte identity and decoded media facts before publishing a handle.
Trusted immutable files may be read directly through the verified handle;
mutable files need a verified snapshot. Missing, duplicated, or mismatched
volumes, symlink escapes, wrong bytes, and wrong decoded shape must be errors.

The host owns credentials, network and repository policy, decoder limits, and
quota-limited Git transport storage. A known-hash download can use retained
verified bytes offline after authorization. Current-URL imports are a separate
host operation and must never silently change a score's content identity.
Remote Git acquisition must stay pinned to a full commit and selected regular
blob; transport-store provisioning and garbage collection remain host work.

Other hosts need a portable export path that copies verified finite bytes below
the package root and rewrites their locations to `relative_file` while retaining
the content hash. Live sources need capture or materialization first.

## Streaming URL adapters

A stream URL identifies a media session, not a sealed file. Its `transport`
selects a host adapter; HTTPS alone cannot distinguish a finite download,
progressive audio, HLS, DASH, or an Icecast response. The host needs transport
capability reports for seekability and window, known extent, startup latency,
timestamp provenance, reconnect behavior, and observed rate and ordered
channels. It must compare those observations with declared facts before output.

Start with forward-only live input. Reconnects, dropouts, format changes, and
clock discontinuities must be visible rather than presented as contiguous
audio. Recording turns received samples into finite fragments, clock
observations, and explicit gaps. Offline rendering rejects an uncaptured live
stream. Opening one source twice does not imply shared consumption; the host
must either open independent sessions or explicitly provide shared fan-out.

## Python buffer providers

A trusted host registration resolves a declared module and function in its own
Python environment. Loading provider code must be opt-in; a score declaration
alone never authorizes an import. The host supplies an `AudioProviderRequest`
containing validated JSON arguments, declared sample rate, ordered channels,
and required frame count, then calls a buffer provider returning one NumPy
array. Put the request protocol and array validation in the host/provider
package; uFor core must not import NumPy or execute provider code.

The returned array must be C-contiguous with shape `(frames, channels)`, dtype
`float32` or `float64`, and finite samples in `[-1, 1]`. Reject rank-one mono,
channel-first, object or integer arrays, wrong extent/layout, nonfinite values,
and mutation of the request. Name the asset and provider in preparation errors.
Do not retry provider failure automatically or catch user interruption as a
normal provider error. A separate materialization operation encodes the result
and records the actual encoding, length, hash, rate, channels, and frames.

## Python callback streams

A callback provider creates one stateful stream and pushes provider-owned
borrowed arrays:

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
```

Each callback receives a C-contiguous `(frames, channels)` `float32` or
`float64` array with at least one frame. The provider may overwrite or reuse
that memory as soon as the callback returns. The consumer must not mutate,
retain, or pass the array or a view to another thread; it copies into owned
storage during the callback when a longer lifetime is needed. This matches
sounddevice and PortAudio-style borrowed callback buffers.

Callbacks are serialized and may have different chunk sizes. Their order
defines the sample stream. Timing and status observations must preserve source
timestamps, overflow, dropped frames, and discontinuities. The host/provider
package defines these observation types. `run()` returns on clean completion
and raises on failure. The host calls `close()` exactly once on completion,
cancellation, or error; it cannot return while a callback is still active.
The callback must not call `close()`. A real-time deadline permits no
backpressure, so missed deadlines appear as status or failure.

For finite declared `frames`, delivery must match the declaration exactly.
Open-ended callbacks cannot be used for deterministic offline rendering.
Seeking and replay require a separate, explicit future contract.

## Python client-buffer streams

A client-buffer provider creates a synchronous stream that fills storage owned
and reusable by the consumer:

```python
class ClientBufferStream(Protocol):
    def read_into(self, destination: numpy.ndarray) -> int: ...
    def close(self) -> None: ...
```

The client supplies a writable, C-contiguous `(capacity_frames, channels)`
`float32` or `float64` array and may reuse it for every call. The provider
writes the first returned number of rows, never retains the destination or a
view, and leaves later rows undefined. A positive count at most capacity is a
valid read, including a short read; zero means clean end of stream. Boolean,
negative, and oversized counts are errors. Calls are serialized and block until
some frames, end, or error; zero cannot mean temporarily unavailable. The
client calls `close()` exactly once on every exit path.

This contract removes required per-chunk array allocation, without promising
allocation-free provider internals. The host chooses buffer capacity from its
engine constraints. Finite extent and offline-render restrictions match the
callback stream contract.

## Resolver capabilities and composition

Host resolvers must report observed encoding or transport, rate, ordered
channels, finite extent when known, content identity for encoded finite bytes,
seekability, and stream timestamps or discontinuities. Compare each applicable
fact with the declaration before use. A mismatch is a preparation error, not
an occasion to silently resample, remap, truncate, pad, or select a different
volume or revision. An explicit import or capture may produce a new definition.

Validate requested operations against resolved capabilities before starting
output. Sample slicing, reverse, mirror, looping, and arbitrary source offsets
require finite random access or a captured realization. A live stream may feed
forward-only live input from its opening point. Offline composition rejects
unresolved streams. An unsupported combination should name both the asset and
the requested operation.

A host resolution policy must list allowed location kinds, URI schemes and
origins, volume IDs, repository origins, stream transports, and Python module
prefixes. Scores never contain credentials. Diagnostics may show redacted
origins and paths but must not expose query secrets, headers, tokens, or
secret-marked provider arguments. Resolvers need bounded decoding and transfer,
path confinement, redirect and address policy, and precise failure categories.

## Sealing and acceptance

A sealed portable package contains finite bytes verified by content identity.
Recs can already export verified finite relative, volume, HTTPS, and Git assets;
other hosts need the same operation. Buffer providers need materialization,
while stream URLs and callback/client-buffer providers need a bounded capture
before sealing. Do not label a stable stream locator as sealed content.

Use local fixtures for volume mapping, symlink escapes, loopback HTTP, bare Git,
finite stream adapters, and provider functions. Cover denied origins/modules,
identity mismatch, redirects, intermittent failure, borrowed-buffer reuse,
short reads, end-of-stream, status, cancellation, and cleanup. Unsupported
seek, reverse, loop, and offline requests must fail before output. Network
tests must not depend on public services. Audio regression files, where output
is compared, use 48 kHz and at least one second.

## Additional work beyond the prompt

None.
