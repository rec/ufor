# Editing and validation boundaries

Ufor models are field-frozen, not deeply immutable. Lists and dictionaries remain
editable authoring values. Editing their contents does not run model validators;
neither does Pydantic's `model_copy(update=...)`. A validated object can therefore
become invalid after an edit. This behavior is intentional for authoring.

Loading through the codec validates the document. `score_toml` revalidates the
current contents before serialization. JSON model dumps alone serialize values;
validate the result when loading it. TOML has no null array element, so a score
containing a decoded OSC null argument is rejected by `score_toml` with a specific
error. JSON preserves that positional argument without loss.

Library normalization validates resolved scores. Composition revalidates and
copies supplied score records, including their nested collections, into its own
registry. Resolving inline scores never adds entries to the caller's registry.
Sample and synth preparation revalidate the instrument before making lifecycle
decisions. Callers must not mutate these prepared records during their use.

Low-level reference calculations take valid definitions as a precondition. After
editing a definition, validate its dumped contents using its model class before
calling these calculations. They do not recursively revalidate on every scalar
observation. Derived musical values are calculated from current contents rather
than cached, so valid edits remain visible.

Public functions do not promise safe concurrent mutation. Author, validate, then
evaluate or prepare; maintain runtime state separately from the definition.

## Portable Python tuning input

Use the existing Pydantic validation context for tuning bodies, source definitions
and tuning score envelopes:

```python
from ufor.tuning import Tuning

tuning = Tuning.model_validate(
    {'source': {}, 'root_frequency': '1 kHz / 3'},
    context={'portable': True},
)
```

The same context works with `model_validate_json` and propagates into nested
sources. It requires actual JSON integer/boolean types, signed 64-bit tuning
integers and the shared tuning unit subset. `parse_score`, `score_toml` and score
migration apply it automatically. JSON model dumps alone do not validate portable
input; validate with the context before serializing authored models.

Ordinary Python construction keeps its integer/boolean coercions and broader
Pint syntax. These conveniences must normalize to portable values before writing
a document. Authoring models may represent out-of-range integers, but portable
validation rejects them and tuning evaluation requires signed 64-bit arguments.
The schema records the portable integer bounds and table limits.

Tuning sources, `Tuning` and `TuningScore` revalidate existing instances, including
when embedded in another tuning model. Validation can create new models and
collections; edit the validated model's own collections, rather than relying on
identity with the original inputs. Invalid edited tuning lists are rejected on
embedding as well as serialization. Current table values are checked during
evaluation, with a 10,000-entry preparation cap. `Computed.as_ratios()` has the
same materialization cap; a computed note count can otherwise span positive i64.

The checked pitch parser is also used by Scala import/export. Out-of-range exact
Scala ratios now fail with `ValueError`. Scale naming, interval calculations,
oscillator phase/duty/gain and general synth cents helpers retain their separate
Python arithmetic. `Scale.frequency()` propagates the supplied tuning's range
and arithmetic errors. These domains have not been ported to Rust.

Recursive composition models support direct construction, validation, and schema
generation from their defining modules. Their model rebuild loads the supported
score union from `ufor.score_types` only when needed; callers need not import
`ufor.codec` for initialization. This applies to `Part`, arrangement models, and
light animation models.

## Schema and semantic validation

Portable modulation definitions use the same explicit validation context as
tuning. Their [shared contract](rust-modulation.md) pins Unicode 15.1.0 identifier
properties, finite scalar input, quantity syntax and aggregate preparation limits.
Ordinary Python authoring retains broader Unicode/Pint/coercion facilities;
portable validation must accept the resulting values before interchange. Other identifier
domains are not implicitly changed to that repertoire except for the explicitly
ported generator definitions described below.

Modulation models and binding leaves revalidate existing instances. Local binding
validation reports unresolved generator/follower references rather than claiming
full instrument or processor validation. Existing complete Python settings still
perform their contextual checks; the native port does not replace those checks
or add generator execution.

Portable [generator definitions](rust-envelfo.md) use the same pinned identifiers,
checked exact quantities and strict scalar/boolean/counter inputs. Context
`max_records` configures the whole generator operation, defaulting to 10,000;
nested definitions and revalidated instances share that limit. Actual edited
values are checked before serialization can normalize them. Inherited child
clock/scope must match the parent. Metadata/reference/event text is limited to
4096 characters, including selectors before canonicalization. Ordinary authoring
keeps its broader unit syntax and existing coercions. Shared segment and captured
approach helpers keep nongenerator level ranges; approach resolution checks
finite intermediates and signed 64-bit derived nanosecond counts.

Generator scores and `instantiate_envelfo` revalidate public declarations and
overrides. Hz public rate parameters require seconds clocks; literal beat-clock
rates remain supported. Scalar materialization uses a checked rational from the
f64 value's shortest decimal spelling. Generator-aware partial binding validation
checks supplied definitions and reports typed outstanding reference, follower,
event and target checks. It shares one configurable budget with embedded
modulation. See the [API guide](rust-envelfo.md). Collection budgets are semantic
and configurable, so the schema does not impose fixed modulation list maxima.

`schema/scores.json`, generated by `ufor.codec.score_schema`, describes the
structural envelope and many scalar constraints. Passing JSON Schema is necessary
but not sufficient for acceptance. Cross-field validators, custom text rules,
and reference-dependent checks are also normative. Implementations must apply
them after structural validation; schema defaults do not resolve inherited
settings or normalize selectors by themselves.

`Asset` is a source declaration, not an acquired payload or a promise that the
bytes are currently available. Assets use one discriminated `location` object.
The source determines which facts are legal:

| Location | Required content identity | Audio extent | Access |
| --- | --- | --- | --- |
| `relative_file`, `volume_file`, `download`, `git_file` | `content` with optional measured byte length and SHA-256 | Required for audio | Finite random access after resolution |
| `stream` | Forbidden | Optional | Sequential unless the host reports seeking |
| Python `buffer` provider | Forbidden | Required | Random access in the returned array |
| Python `callback` provider | Forbidden | Optional | Provider-owned sequential push |
| Python `client_buffer` provider | Forbidden | Optional | Client-owned sequential pull |

Relative and volume/Git member paths are portable POSIX paths below their
declared root. Downloads require an absolute credential-free HTTPS URL and no
fragment. Git locations require an absolute supported repository URI, a full
lowercase object ID, and a portable blob path. Stream URLs are absolute and
credential-free. Provider modules are dotted Python names, functions are Python
identifiers, and arguments contain recursive finite JSON values only. Provider
arguments are limited to 10000 values and 64 nesting levels. `parse_score`
accepts at most 16777216 TOML characters, 100000 decoded values, and 64 decoded
nesting levels; larger documents fail validation.

Validation grants no authority to read a volume, open a network connection,
contact Git, import Python, or decode media. Hosts resolve those declarations
under explicit policy and compare observed facts with the score before use.
Ufor performs no acquisition while parsing, validating, or generating schema.
Finite source types describe materializable output, but a Python `buffer`
provider has no pinned byte identity until a host materializes it.

Score version 4 introduces structured locations. `codec.migrate_score_v3`
accepts a decoded version 3 score, converts its relative `path`, `byte_length`,
and `sha256` asset fields to `location` and `content`, advances the version, and
validates the result. It does not mutate the supplied dictionary or overwrite a
file. Version 4 models do not accept the removed fields.

Identifiers deliberately preserve Unicode. For each code point, the first must
have the Unicode Lowercase property; remaining code points must have Lowercase,
Numeric_Type Decimal or Digit, or be ASCII `-` or `_`. This matches Python's
single-character `islower` and `isdigit` predicates. There is no normalization,
case folding, transliteration, or locale-dependent comparison. Thus `é2` and
`a²` are valid, while uppercase letters and decomposed combining marks are not.
Consumers must agree on Unicode property data for newly assigned characters;
the conformance file pins examples of accepted and rejected existing characters.
Identifiers are not the same type as library/score display names.

Literal selectors have separate rules:

- Library names are nonempty, trimmed and contain no `:`, `#`, or `/`.
- Score names also reject `.*`. Internal spaces remain literal.
- A tag starts with `#` and has a nonempty value containing no whitespace,
  `:`, `#`, or `/`. Repeated tags are deduplicated in first-occurrence order.
- Addresses start with `/`, reject `:`, `#`, and backslashes, and have nonempty,
  trimmed components other than `.` or `..`.
- Selector parsing trims the surrounding library, name, tag and address pieces;
  it does not interpret a regex, shell glob, or quoting language.

The remaining semantic rules are grouped by their defining format documents:

| Domain | Required checks beyond basic shape |
| --- | --- |
| [Composition](composition-implementation.md) | Unique IDs, one reference selection, existing public targets, acyclic graphs, single input writers, compatible clocks/layouts, exact integer conversion and parameter-domain narrowing |
| [Instruments](instrument-format.md) | Existing asset/group/selection/control references, effective inherited settings, spatial layouts, legal trigger mappings, choke/sustain/articulation contracts and supported preparation profile |
| [Modulation](modulation-format.md) and [automation](automation-format.md) | Ordered points/events, valid domains, scope/unit compatibility, writer combination and envelope/LFO time/polarity constraints |
| [Bindings](binding-format.md) | Complete numeric domains or enum tables, monotone endpoint-covered piecewise mapping, distinct native targets and existing stream references |
| [Fixtures](fixture-format.md) | Matching parameter/encoding domains, complete choices, distinct slots, valid cue values and noncolliding physical footprints |
| [Slideshow](slideshow-format.md) and [broadcast](broadcast-format.md) | Existing assets/sources, adjacent unique transitions, effective cue rules, caption language, acyclic timing dependencies and ordered run events |
| [Musical definitions](musical-format.md) | Positive pitch expressions, finite/repeating table bounds, strict interval input and the explicitly permissive Scale editing contract |

These rules apply to decoded values, not just one wire syntax. Portable rejected
examples live in [validation.json](../conformance/validation.json); they are
representative boundary cases, not an exhaustive substitute for the format rules.
Shared lifecycle examples live in
[instrument-lifecycle.json](../conformance/instrument-lifecycle.json). The Python
tests consume the same examples as a reference for other implementations.
