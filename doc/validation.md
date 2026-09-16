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
