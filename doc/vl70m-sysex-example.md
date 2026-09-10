# VL70m: an incomplete SysEx description that still supports a librarian

Status: design example, not a new accepted score kind or MIDI implementation.
The first operation is lossless reading and explicit patch relocation. No hardware
was contacted, and no sampler or general SysEx description language is proposed.

## What this example establishes

A MIDI description need not decode every sound parameter to be useful. It can
recognize one message family, expose a few fields, preserve the remainder and
support a small, precisely bounded edit. Unknown data is material to retain,
not a reason to fill fields with defaults or discard the message.

The evidence is Tom's [VL70 librarian](../../sysexy/sysexy/vl70.py), its
[bank-writing caller](../../sysexy/sysexy/write.py), and the local `.syx` files.
The source checkout was `5867e142cbda668feda1efefea5321bcdef1d068` with no local
changes. SHA-256 of `vl70.py`:
`8fd440195fd432f8b336acccf3333d5df37d0fc6b26bac6d0d2bdbe3cde8c360`.
Inspection date: 10 September 2026.

Yamaha's indexed [VL70m List Book MIDI data format, printed page 30](https://data.yamaha.com/files/download/other_assets/7/314687/VL70mG2.pdf)
describes native bulk messages with byte counts, a three-byte address, payload
and checksum. It specifies a checksum covering count, address and data, and
encodes the device number in `0n`. That agrees with the local evidence below.
Direct PDF retrieval returned HTTP 403; the full parameter tables were not
reviewed. The index field's meaning and accepted relocation range below are
based on the librarian and its corpus, not a claim to have verified all Yamaha
address tables.

## What was observed

All 17 files below were inspected as bytes without invoking the librarian.
They contain 1,344 messages, including 765 distinct complete byte strings.
Repeated exports and concatenations are not independent device observations.

| Local files under `sysexy/syx` | Files | Messages per file | Total |
| --- | ---: | ---: | ---: |
| `old/sources/*.syx` | 8 | 64 | 512 |
| `old/*.syx` | 3 | 64 | 192 |
| `prog/A.syx`, `prog/B.syx`, `vl70/A.syx`, `vl70/B.syx` | 4 | 128 | 512 |
| `prog.syx`, `vl70.syx` | 2 | 64 | 128 |

Every message is 174 bytes, starts with `F0`, ends with `F7`, and has seven-bit
interior bytes. There are no bytes outside messages and no broken framing in
this corpus. All names occupy eight printable ASCII bytes. Device byte `00`
occurs 640 times and `01` occurs 704 times. All slot values are between 0 and 63.
The 128-message files repeat slot values: file order and destination slot are
separate facts. Patch titles can also repeat.

These counts establish support for the observed family only. They do not prove
that every VL70m dump has this layout or that all messages have been exercised
against both physical instruments. File names alone do not establish which
hardware modification produced a file.

## The narrowly understood message

Offsets below are zero-based; byte intervals are half-open. Hexadecimal values
have a `0x` prefix. The 174-byte size includes framing and checksum.

| Bytes | Interpretation for this example | Evidence and edit policy |
| --- | --- | --- |
| `0` | `0xF0` start | Corpus; required for recognition |
| `1` | `0x43` Yamaha identifier | Librarian and corpus; fixed |
| `2` | Bulk-message class plus wire device number, `0n` | Corpus has only 0 and 1; preserve unless explicitly retargeting |
| `3` | `0x57` model/format selector | Corpus; other selectors are outside this example |
| `[4,6)` | Two seven-bit count bytes, `0x01 0x23` | `(1 * 128) + 35 = 163` payload bytes |
| `[6,8)` | Address prefix `0x40 0x00` | Corpus; do not edit |
| `8` | Destination slot | Librarian relocates this byte; this profile allows 0–63 |
| `[9,17)` | Eight raw patch-title bytes | Librarian displays this region; display without rewriting it |
| `[17,172)` | 155 uninterpreted payload bytes | Preserve exactly, including zeros and padding |
| `172` | Seven-bit checksum | Validate before permitting relocation |
| `173` | `0xF7` end | Corpus; required for recognition |

The complete payload is `[9,172)`, 163 bytes. Preserving unknown bytes does not
mean excluding them from the checksum.

For a message `m`, the observed checksum rule is:

```text
checksum = (-sum(m[4:172])) mod 128
valid    = sum(m[4:173]) mod 128 == 0
```

All 1,344 messages satisfy this rule. All instead have residue 28 when summing
`m[7:173]`: the omitted count bytes and high address byte sum to 100, and
`(100 + 28) mod 128 == 0`. This explains why the librarian's `checked_bytes`
property (`data[7:-2]`) is not the complete checksum-covered region.

Changing only the slot from `old` to `new` permits the librarian's incremental
rule `new_checksum = (old_checksum - (new - old)) mod 128`. It is correct for a
previously valid message. The example requires validating the original checksum
first and recomputing the full checksum afterward. Retargeting byte 2 does not
affect this checksum because it lies outside the covered interval.

The wire device number is not the MIDI note channel, a network port, a patch
name or a modification identifier. Its proposed legal encoding is 0–15 under
the `0n` rule; values other than 0 and 1 are not exercised by this corpus.
Reject out-of-range values rather than apply the librarian's `% 128`, which
could change the message class as well as the device number.

## How this fits Ufor

Keep three reusable descriptions distinct from the application's device setup:

1. **MIDI implementation description:** the recognized message layout, known
   fields, checksum rule and permitted edits above. A device-specific encoder
   and decoder can implement it; this example does not require a declarative
   language powerful enough to express every manufacturer's protocol.
2. **Patch material:** the original complete SysEx asset plus ordered entries
   locating messages by byte offset and length. The asset's measured length and
   SHA-256 use Ufor's existing asset vocabulary. Decoded titles and slot numbers
   are views of those bytes, not independently authoritative patch values.
3. **Instrument capabilities:** any understood musical controls and their MIDI
   mappings. None are invented from the opaque 155 bytes in this example.
   Unknown parameters are not exposed as `ParameterExport` declarations.

A future patch score could name the MIDI description using `ScoreVersion` and
locate its original asset. It would describe saved instrument state, not a timed
performance sequence. The current `InstrumentScore` describes sample instruments;
forcing a VL70m patch into its sample slots would give those fields the wrong
meaning. A new patch/MIDI score kind needs a separate implementation decision.
No TOML examples here pretend such a kind is already accepted by the codec.

For example, a library entry named `lead-choice` could locate message 65 in a
128-message file. Its title comes from that message's raw title bytes. A request
to export it to slot 7 concerns that occurrence, even if another message has the
same title or the same original slot. A relocation request is a transient
operation on patch material, not a permanent rewrite of the imported original.

The local setup gives the two physical instruments separate names, for example
`vl70-stock` and `vl70-patchman`, and records their connection and wire device
number. The Patchman label records the user's knowledge; neither device number
nor the observed header identifies the modification. Share the understood wire
description where applicable, but retain the source instrument/configuration
with a patch when known. Unknown provenance stays unknown. Protocol acceptance
does not establish identical sound or patch compatibility between configurations.

MIDI-CI Profiles, factory-program naming, full instrument parameter editing and
modification discovery are outside this first example.

## Reading and preserving incomplete material

Import retains the exact source file as the authoritative asset. A recognized
entry records its original byte location; equal byte strings need not lose their
separate occurrences. An unchanged export is byte-for-byte identical, including
message order, padding and any unrecognized material.

Recognition checks framing, fixed header fields, seven-bit data and declared
length. Relocation additionally requires a valid checksum and the understood
address family. An unknown message, another dump length, invalid checksum or
malformed file remains available as opaque material with a diagnostic, but this
operation cannot edit it. Do not silently repair a checksum, remove bytes or
reinterpret a message as this family merely because it begins `F0 43`.

Display decoding must not normalize, truncate, strip or replace the raw title
bytes in storage. A label the user adds to a library entry is separate from the
embedded patch title. Editing the embedded title is deliberately deferred here.

## Relocating a patch

Given a validated original and explicit destination slot, plus an optional new
wire device number:

1. Check the requested slot is an integer in 0–63. If provided, check the device
   number is an integer in 0–15. Booleans are not numeric destinations.
2. Copy the complete original message. Change byte 8 and, if requested, byte 2.
3. Recompute byte 172 from bytes `[4,172)` and validate the resulting checksum.
4. Verify that every other byte is identical to the original; return new bytes.

Do not change the in-memory imported object, silently renumber a bank on save,
or truncate a 128-entry library to 64 entries. Writing an explicit selection
of entries to destination slots is a different operation from preserving a file.
A destination bank export must specify its mapping and reject duplicate slots
unless the caller explicitly requests an ordered sequence of overwrites.

The existing `VL70.write` renumbers and mutates its inputs. Its caller also
truncates selections longer than 64, and repeated uses can share mutable patch
objects. Those behaviors must not become Ufor's ordinary save semantics.
The cached title and `checked_bytes` views can become stale if `data` changes.
These are design observations; this work does not change the working librarian.

## A synthetic acceptance example

This vector contains no captured or commercial patch data and makes no claim
to produce a usable sound. It is a byte-format test, not material to transmit.
Construct its 174 bytes by concatenating:

```text
F0 43 00 57 01 23 40 00 00
ASCII bytes for "UFORTST " (eight bytes, including the trailing space)
155 zero bytes
45 F7
```

The checksum is `0x45`. SHA-256:
`ab4eb024a4089579b5aa5c09b7d848a7fdca9925d76f90771a93758ee146bd9b`.
Relocate to slot 7 and wire device 1. Only offsets 2, 8 and 172 change, to
`0x01`, `0x07` and `0x3E` respectively. The result's SHA-256 is
`cdb397f497e731e4f1cceb291a1692e6739a51a3093f02e8753b93c2cc678321`.
Relocating back reproduces the original bytes and hash.

A later implementation must also pass these cases:

| Case | Required result |
| --- | --- |
| Unchanged file, including duplicate titles and repeated slots | Exact byte-for-byte export |
| Same imported patch selected twice for two destinations | Two independent results; original remains unchanged |
| Edit slot only; edit device only | Only the requested field and any checksum consequence change |
| Slot 0 and 63 | Accepted for this layout |
| Slot -1 or 64; device -1 or 16; fractional or boolean input | Rejected without mutation |
| Unknown payload changed in a synthetic fixture, checksum updated | Payload preserved through relocation |
| Bad checksum, count mismatch, unfamiliar header or framing errors | Original retained; relocation unavailable with a precise diagnostic |
| Two equal titles or two equal source slots | Both occurrences remain independently selectable |
| Stock versus modified target with unverified compatibility | Keep the uncertainty visible; no promise of equivalent sound |

## What remains before execution

First implement a pure decoder and copy-on-edit relocation operation against
these vectors, using Sysexy for file acquisition if appropriate. Next compare
candidate outputs with local captured bytes. Hardware transfer, request/reply
handling, pacing, acknowledgements and actual restoration require separate work.
Recorded examples and successful checksum checks do not prove device behavior.

Full parameter tables, title editing, additional address families, program
selection, MIDI-CI discovery and generalized SysEx schemas can follow when a
concrete operation requires them. This example establishes partial knowledge and
lossless editing without assuming those larger designs are finished.

## Additional work beyond the prompt

None.
