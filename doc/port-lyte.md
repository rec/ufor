# lyte integration

The port to Ufor light scores is implemented. Ufor owns portable effect settings,
layouts, composition, selectors, and public parameter contracts. lyte owns frame
generation, mutable renderer state, installation/device configuration, preview,
and physical output. There is no Ufor dependency on lyte or NumPy.

## Loading and preparation

Use `library_files.read_library(config_path)` for explicit local discovery and
`library.composition(selector, parameters)` for the resolved graph. Reading does
not create a library. Report diagnostics and reject missing or unsupported
selected dependencies before output; unrelated rejected entries need not prevent
selection of a usable score.

`entry.score` is the authored definition. `entry.resolved` and `library.records`
contain normalized execution descriptions; their synthetic dependency paths
must not be saved as authored references. Follow `entry.content_origin` for
inherited asset roots and Python implementations. Configured Python libraries
execute trusted local code; they are not sandboxed plugins.

Hosts select the light output, public parameters, and installation wiring
separately. Renderer registries map the declared effect tags to installed
implementations. Scores do not contain arbitrary renderer import paths.
Unsupported effects or component contracts must fail during preparation.

## Frames and timing

Generic composition uses the full `LightType`: ordered lights, components,
interpretation, and logical rate. Extracted RGB effects require their declared
RGB drive contract. Do not infer extra channels or color-space conversions.
Apply installation wiring once after logical composition.

One prepared part owns one state: multiple reads of its output at the same tick
must not advance it repeatedly. Separate parts retain independent state even
when they use the same definition. Cue activation begins the child's local
clock at zero; seeking a stateful effect requires replay or a valid checkpoint.
The [light format](light-format.md) defines clipping, placement, crossfades,
controls, and exact logical-clock semantics.

## Evidence boundaries

Ufor's fixtures cover geometry, wiring, composition math, and scalar controls.
They do not establish exact cross-language equivalence for stochastic effect
renderers. That requires renderer fixtures with specified RNG initialization,
step order, precision, reference revision, and tolerances.

Physical Twinkly and Art-Net behavior remains deployment-specific validation;
model acceptance and renderer unit tests cannot establish device output. Consult
lyte's current tests and deployment records for that evidence rather than the
historical port's test totals or dependency revisions.
