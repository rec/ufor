# Portable SoundSettings

The base settings body combines sound processing, an optional amplitude
Envelope, named generators, modulation, bindings and generator event
connections. Rust exposes it in `ufor::samples::processing`. Python exposes it
in `ufor.samples.processing`. Both codecs read and write settings bodies as
JSON or TOML. Instrument and effect scores keep their existing formats.

## Processing declarations

An omitted `processing` uses zero volume adjustment, tuning, pan and stereo
balance, normal polarity, no EQ or filters, and filters before amplitude.
EQ bands require a name, positive frequency and resonance, and finite gain.
An EQ band defines an RBJ peaking biquad at a requested output rate. Resonance
is the Cookbook Q and the center response is the authored gain in decibels.
Coefficient preparation requires a frequency strictly below Nyquist and
rejects results outside finite arithmetic.
Resonant filters require a name, response and positive cutoff. They default to
one stage, Q of `1 / sqrt(2)`, error at the cutoff boundary, minimum 1 Hz,
Nyquist ratio 0.999 and tolerances of `1e-12` for coefficients and `1e-6` dB
for response. EQ and filter lists retain order and enforce uniqueness within
each list. Their target namespaces remain separate.

Portable decoding permits the shared quantity grammar on Hz, dB and cent
fields that accept quantities. Pan, balance, Q, resonance, coefficient
tolerance and Nyquist ratio require finite numbers. Polarity inversion
requires a boolean, and the stage count is the integer 1 or 2. Python
authoring constructors retain their wider input facilities. The portable
path revalidates existing instances and their nested declarations.

## Target facts and context

Call `resolve_target` with the same `Target` used for a modulation declaration.
It returns a unit, scalar default, minimum rule and any required Envelope
scope. Duration targets also carry the exact rational before conversion to
the scalar default. The supported address families are:

| Target name | Parameters |
|---|---|
| `processing` | `amplitude` (ratio with default 1), `volume_db`, `tuning_cents`, `pan`, `stereo_balance` |
| `eq-<name>` | `gain_db`, `frequency_hz`, `resonance` |
| `filter-<name>` | `cutoff_hz`, `q` |
| `envelope`, `envelfo-<name>` | `on-<index>-duration`, `release-<index>-duration`, and the corresponding `time_constant` fields |

Envelope indices start at zero. Finite segment duration units follow the
Envelope clock. Captured approaches expose a time constant in seconds.
Indefinite holds have no duration target. Amplitude needs a nonnegative
domain, resonance and Q need positive domains, and multiplicative route points
must be nonnegative. Envelope timing routes latch from key or velocity.
Filter defaults are authored values. The host supplies the sample rate to
`ResonantFilter::cutoff_bounds` and chooses its renderer profile.
`FilterBoundary::resolve` applies error or clamp to the prepared inclusive
bounds without allocating. `biquad_coefficients` matches Python's normalized
RBJ reference coefficients. The [filter cases](../conformance/filter-cutoff.json)
exercise all four responses and cutoff boundary handling.

When a named generator is a reference, lookup returns an outstanding
generator target with its known scope. Unknown local addresses fail.
`validate_context` also reports generator binding, connection and control
requirements. Omit the control map to keep its checks outstanding. Supplying
an empty map asserts that no controls exist. A caller materializes a generator
outside the library and validates the resulting settings again. Use
`require_complete` to reject any outstanding checks in the resulting report.

```rust
use ufor::codec::{self, Format};
use ufor::envelfo::PreparationLimits;
use ufor::identifier::Identifier;
use ufor::modulation::{Target, Unit};
use ufor::samples::processing::TargetResolution;

let limits = PreparationLimits::default();
let settings = codec::parse_sound_settings(
    r#"{"processing":{"volume_db":"-6 dB"}}"#, Format::Json, limits,
)?;
settings.validate_context(None, limits)?.require_complete()?;
let target = Target::new(
    Identifier::new("processing".into())?,
    Identifier::new("volume_db".into())?,
);
let TargetResolution::Resolved(value) = settings.resolve_target(&target)? else {
    unreachable!("processing targets are local");
};
assert_eq!((value.unit, value.default_value), (Unit::Db, -6.0));
# Ok::<(), ufor::error::Error>(())
```

```python
from ufor.codec import parse_sound_settings
from ufor.modulation import Target

settings = parse_sound_settings('{"processing":{"volume_db":"-6 dB"}}', 'json')
settings.validate_context().require_complete()
target = settings.resolve_target(Target(name='processing', parameter='volume_db'))
```

For already decoded Python data, use
`SoundSettings.model_validate(data, context={'portable': True})`. Both
preparation APIs default to 10,000 records and accept an explicit override.
Each operation counts the root, present Processing, Envelope, modulation and
tolerance objects, EQ and filter entries, and embedded generator, source,
target, route, point, binding and event records. Context validation includes
supplied controls in that budget. Defaults omitted from the wire do not add
singleton records. Text parsing also applies separate character, value and
depth limits. See the [shared cases](../conformance/sound-settings.json).

The shared body resolves the base families above. FM, sample inheritance,
channel routing, and effect processor targets use their own Rust modules.
Use `codec::parse_sound_settings_with_targets` with `Fm::resolve_target`
to validate an FM voice's settings against its graph and shared processing
addresses together. A resolved target checks its unit, authored default,
scope when specified, and minimum domain through
`ResolvedTarget::validate_parameter`. Enge uses the same checks when it
prepares native modulation slots. The
[shared FM cases](../conformance/fm-graph.json) cover mixed target families.

Use `samples::routing::spatial_bounds` to compute each pan or balance range
from an instrument or effective slot settings layer. Delayed or fading inline
LFOs include the neutral route contribution during activation. Materialize
generator references before using these bounds for playback.
`validate_sampler_spatial` checks that the combined ranges stay within
`[-1, 1]`. See the [shared sampler cases](../conformance/sampler-spatial.json).

Yamaha target resolution, host indices, renderer support,
resource resolution and rendering sit outside this body.
