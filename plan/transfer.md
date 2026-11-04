# Pending metadata decision

`pyproject.toml` currently advertises only the Python 3.15 classifier while
`requires-python` is `>=3.13`. The user previously requested consistency: either
omit Python-version classifiers or list every supported version. The choice
between those policies remains unresolved; the earlier recommendation to remove
the classifier was not an accepted implementation decision.

Do not change dependency or Python support policy as part of documentation
maintenance. Once the classifier policy is decided and implemented, remove this
plan.

## Additional work beyond the prompt

None.
