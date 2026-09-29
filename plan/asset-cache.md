# Asset cache: remaining host work

The finite-byte cache lives in reccy, and uFor contains only portable asset
source declarations. See [asset locations](url-paths.md) for unresolved host
resolution and stream-provider work. This plan tracks the cache behavior that
is still missing; implemented APIs are documented in reccy's
`doc/shared-features.md`.

## Host acquisition and identity

Hosts must authorize every acquisition independently of its source fingerprint.
Complete fingerprint inputs include package identity for relative paths, measured
volume ID for volume paths, and effective provider arguments, rate, channels,
implementation version, and encoding settings for generated output. Credentials
and signed lookup secrets stay in host configuration, not score or ordinary cache
metadata. Recs already resolves finite relative, volume, HTTPS, and Git assets for
offline editing and package export; its other consumers and other hosts still need
explicit policy and resolver integration.

Current-URL HTTPS imports in reccy need host integration. A known-hash uFor asset
can use retained verified bytes offline after the host authorizes that asset;
that is separate from asking for a URL's current representation. The host must
keep request credentials private and must not turn a changed response into a
silent score update. Test current-URL imports with a loopback server covering
missing expiry, variants, conditional validation, redirects, identity mismatch,
interrupted transfer, and offline reuse. Do not depend on public services.

Remote Git acquisition exists in reccy and is available through recs' finite
resolver. Other consumers still need host authorization and integration. A bare
Git transport repository needs automatic provisioning, a hard storage quota,
and garbage collection separate from the verified asset object store. Fetching a
commit/path-selected blob can require additional repository objects; no host
should promise a single-object transfer.

## Provider values and derived assets

A trusted host may register a finite buffer provider as deterministic only when
its contract covers all inputs and environment dependencies that can change the
bytes. The value key must include provider identity and implementation/dependency
version, canonical effective arguments including defaults, resolved rate,
ordered channels, frame count, output dtype, protocol version, and materialization
format and encoder settings. An implementation version is a host-managed
contract, not merely a hash of function source. Reccy can retain verified bytes
under a host-supplied key and detect conflicting regeneration; invoking the
provider, resolving arguments, validating arrays, and encoding audio remain host
work.

Nondeterministic buffer output may be explicitly materialized as a new entry on
each call. A lossless array representation must preserve dtype, shape, samples,
rate, and channel order. Quantization, resampling, lossy encoding, thumbnails,
waveforms, and indexes are distinct derivatives whose keys include source
identities and transform settings/version. Define their dependency roots so
collection cannot remove required parents or leave unusable derivative records.
A deterministic value may be collected unless pinned or protected; a forever
protection promise must fail admission when it cannot fit available capacity.

## Stream capture and portable export

Connect streaming URL, callback, and client-buffer host adapters to reccy's
bounded `CaptureSession`. Copy borrowed callback samples before returning and
never perform filesystem I/O in the callback. Consume valid client-buffer rows
before reusing storage. Preserve source timing, discontinuities, gaps, media
facts, and actual termination reasons. Providers must close on clean stop,
cancellation, and failure according to their protocol.

A captured realization needs a host path into a sealed uFor recording score.
Export a selected capture as finite relative assets and verified recording
fragments and gaps, never as another live locator or an assumed complete extent.
Reccy's single-entry export and recs' finite package export do not yet provide
that capture-to-score conversion.

## Host retention policy

Define an understandable host configuration that maps to reccy's asset and
capture retention rules. Rules are additive: recent duration and newest-N can
both retain a record, while pressure may override retention but never roots or
protection. Validate ambiguous or contradictory configuration before running
collection. Explain matching rules, roots, ranks, deadlines, and pressure
behavior to an operator. HTTP freshness determines current-URL reuse and is not
a retention promise; only download entries may use `while_fresh`.

Derived-object dependency retention remains to be integrated. Imports explicitly
saved by a user should receive a durable root. Capture and recovery records
without roots expire under capture retention rules, and a subsequent asset
collection reclaims released fragment entries.

## Capacity and incomplete-session recovery

Add pressure collection to admission so the cache can reclaim eligible entries
before reporting insufficient space. If protected bytes prevent admission,
report the required bytes and the blocking roots without silently unpinning or
overwriting anything. Reserve capacity for a capture before starting it and
extend the reservation as bounded fragments arrive. Count published objects,
staging, incomplete capture material, and recovery evidence. Git transport
storage needs its own hard quota and collection path.

Reccy can now identify abandoned staging files, orphan objects, and dead reader
leases without treating live work as stale. Incomplete capture sessions still
need durable ownership and an explicit salvage or discard action. In particular,
a crash between deleting a capture record and releasing its fragment pins can
leave a pin requiring operator review. Do not infer that such fragments are
abandoned from elapsed time alone. A recovery dry run should show their sizes
and available actions; execution must recheck ownership and roots before
deletion.

## Remaining acceptance

- Integrate finite-asset policy in recs consumers beyond offline edit and
  package export, plus other hosts that use uFor assets.
- Materialize provider output and derivatives under complete value keys, then
  export captured streams as portable recording scores.
- Exercise pressure admission, protected-space failures, capture reservations,
  transport quotas, and incomplete-session recovery with local fixtures.
- Give hosts operations to resolve, import, materialize, capture, open, export,
  explain, and inspect. Distinguish misses, denied acquisition, wrong identity,
  corruption, incomplete capture, provider failure, and insufficient space.

Audio regression artifacts, where output is compared, use 48 kHz and at least
one second.

## Additional work beyond the prompt

None.
