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
input/output ranges, conversion, and update resolution. Supported conversions are
identity, affine, logarithmic normalization, and ratio-to-dB. Ratio zero maps to
an explicit native mute (`null` from `map_parameter`), never a fictitious finite
dB value. Values outside either declared domain are rejected.
