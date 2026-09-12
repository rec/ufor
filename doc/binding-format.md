# Bindings

A binding score connects one portable definition to a named host adapter. It has
no device address, credentials, executable path, or network operation. Hosts use
the adapter name to locate installed code and verify declared capabilities before
any output starts.

The first concrete binding is [the VL70m librarian example](../examples/bindings/vl70m.toml):
`sysexy.vl70m` identifies the existing librarian adapter and its observed bulk
message family. It preserves and relocates SysEx through the host; Ufor does not
open a MIDI port.

Each parameter map declares its canonical name, stable native ID, unit, finite
input/output ranges, conversion, update resolution, and range policy. Supported
numeric conversions are identity, affine, logarithmic normalization, ratio-to-dB,
and monotone piecewise tables. Discrete parameters use an explicit enum table.
Ratio zero maps to an explicit native mute (`null` from `map_parameter`), never a
fictitious finite dB value. `map_enum_parameter` maps discrete values.

Bindings also declare typed stream contracts, their logical-to-native channel
maps, and incoming physical controls. Controls retain protocol field, source and
target units, conversion, scope, and reset semantics. This is portable adapter
metadata; a host alone resolves an actual MIDI, audio, or network endpoint.

Opaque implementation state is a sealed `Asset`. When it accompanies canonical
parameters, it has the only supported restore order: opaque state first, then
canonical values. This keeps canonical score values authoritative while retaining
implementation-specific detail.
