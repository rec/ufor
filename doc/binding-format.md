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

Bindings also declare stream capability summaries, their logical-to-native channel
maps, and incoming physical controls. Controls retain protocol field, source and
target units, conversion, scope, and reset semantics. This is portable adapter
metadata; a host alone resolves an actual MIDI, audio, or network endpoint.

Input controls use the shared `Scope` vocabulary: `instrument` (the default),
`part`, or `voice`. The former `global` and `performance` spellings are replaced
by `instrument` and `part`; they are no longer accepted. Trigger scope is not
supported by binding input controls.

`StreamContract` describes adapter capabilities, not complete public-port
compatibility. Its `audio` family corresponds to public sampled audio amplitude;
`light` corresponds to sampled light, while `event` and `control` identify those
public stream families. For audio, `channels` is a count and `rate` is samples
per second. These do not name a channel layout or a score timebase. Other families
omit those fields and do not describe event kinds, control quantities/units, or
light layouts. Hosts must consult the definition's full public-port contracts
when checking compatibility; matching these summaries alone is insufficient.

Opaque implementation state is a sealed `Asset`. When it accompanies canonical
parameters, it has the only supported restore order: opaque state first, then
canonical values. This keeps canonical score values authoritative while retaining
implementation-specific detail.

Numeric maps require all four input/output bounds. Piecewise points must start
and end at the declared input endpoints, increase in input, remain monotone in
output, and stay inside the output range. Values outside the input range follow
`out_of_range`; there is no implicit extrapolation. Enum tables omit numeric
bounds and reject them if supplied.
