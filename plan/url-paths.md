# Asset locations: remaining host work

uFor's structured location models and validation are described in
[validation](../doc/validation.md). This plan covers host acquisition, live
sources, Python providers, capability checks, and sealing that remain outside
the portable format library. The related storage work is in the
[asset cache plan](asset-cache.md).

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
