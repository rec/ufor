"""Shared tuning contract and separately identified Python characterization."""

import json
from fractions import Fraction
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, Field

from ufor.base import Model
from ufor.codec import parse_score, score_toml
from ufor.expression import evaluate
from ufor.musical import TuningScore
from ufor.tuning import Computed, FrequencyTable, IntervalPattern, RatioTable, Tuning


class Lookup(BaseModel, frozen=True):
    note: str
    exact: str | None = None
    approx: float | None = None
    outside: bool = False
    error: Literal['nonpositive-result', 'arithmetic-range'] | None = None


class DefinitionCase(BaseModel, frozen=True):
    id: str
    model: Literal['computed', 'ratios', 'intervals', 'frequencies', 'tuning', 'score']
    input: dict[str, object]
    normalized: dict[str, object] | None = None
    lookups: list[Lookup] = Field(default_factory=list)
    as_ratios: dict[str, object] | None = None
    decision: str | None = None


class ExpressionCase(BaseModel, frozen=True):
    text: str
    exact: str | None = None
    approx: float | None = None
    rejected: bool = False


class BudgetCase(ExpressionCase, frozen=True):
    id: str
    operation: Literal['pad_right', 'parentheses', 'unary_plus']
    count: int


class PreparationCase(BaseModel, frozen=True):
    id: str
    model: Literal['computed', 'ratios', 'intervals', 'frequencies']
    count: int
    rejected: bool


DATA = json.loads((Path(__file__).parents[1] / 'conformance/tuning.json').read_bytes())
MODELS: dict[str, type[Model]] = {
    'computed': Computed,
    'ratios': RatioTable,
    'intervals': IntervalPattern,
    'frequencies': FrequencyTable,
    'tuning': Tuning,
    'score': TuningScore,
}
VALID = [
    DefinitionCase.model_validate(c)
    for c in [*DATA['valid'], *DATA['python_characterization']['valid']]
]
INVALID = [
    DefinitionCase.model_validate(c)
    for c in [*DATA['invalid'], *DATA['python_characterization']['invalid']]
]
EXPRESSIONS = [
    ExpressionCase.model_validate(c)
    for c in [*DATA['expressions'], *DATA['python_characterization']['expressions']]
]
BUDGETS = [BudgetCase.model_validate(c) for c in DATA['expression_budgets']]
PORTABLE_INVALID = [
    DefinitionCase.model_validate(c) for c in DATA['approved_contract']['invalid']
]
PORTABLE_EXPRESSIONS = [
    ExpressionCase.model_validate(c) for c in DATA['approved_contract']['expressions']
]
PORTABLE_ERRORS = [
    DefinitionCase.model_validate(c)
    for c in DATA['approved_contract']['evaluation_errors']
]
PREPARATION = [
    PreparationCase.model_validate(c)
    for c in DATA['approved_contract']['preparation_budgets']
]


@pytest.mark.parametrize(
    'case', [c for c in PREPARATION if not c.rejected], ids=lambda c: c.id
)
def test_preparation_accepts_tables_at_limit(case: PreparationCase) -> None:
    prepare_table(case)


@pytest.mark.parametrize(
    'case', [c for c in PREPARATION if c.rejected], ids=lambda c: c.id
)
def test_preparation_rejects_tables_over_limit(case: PreparationCase) -> None:
    with pytest.raises(ValueError):
        prepare_table(case)


@pytest.mark.parametrize('case', PORTABLE_INVALID, ids=lambda c: c.id)
def test_portable_input_types_reject_coercion(case: DefinitionCase) -> None:
    with pytest.raises(ValueError):
        MODELS[case.model].model_validate(case.input, context={'portable': True})


@pytest.mark.parametrize('case', PORTABLE_EXPRESSIONS, ids=lambda c: c.text)
def test_portable_expression_grammar(case: ExpressionCase) -> None:
    check_number(evaluate(case.text), case.exact, case.approx)


@pytest.mark.parametrize('text', DATA['approved_contract']['invalid_expressions'])
def test_portable_expressions_reject_integer_overflow(text: str) -> None:
    with pytest.raises(ValueError):
        evaluate(text)


@pytest.mark.parametrize('case', PORTABLE_ERRORS, ids=lambda c: c.id)
def test_portable_evaluation_failures_are_explicit(case: DefinitionCase) -> None:
    definition = MODELS[case.model].model_validate(
        case.input, context={'portable': True}
    )
    assert isinstance(definition, (Computed, RatioTable, IntervalPattern, Tuning))
    for lookup in case.lookups:
        assert lookup.error is not None
        message = 'positive' if lookup.error == 'nonpositive-result' else '64-bit'
        with pytest.raises(ValueError, match=message):
            definition(int(lookup.note))


@pytest.mark.parametrize('case', VALID, ids=lambda c: c.id)
def test_definitions_match_shared_tuning_cases(case: DefinitionCase) -> None:
    context = {'portable': case.decision is None}
    definition = MODELS[case.model].model_validate(case.input, context=context)
    if case.normalized is not None:
        assert definition.model_dump(mode='json') == case.normalized
    assert (
        type(definition).model_validate_json(
            definition.model_dump_json(), context=context
        )
        == definition
    )
    tuning = definition.body if isinstance(definition, TuningScore) else definition
    assert isinstance(
        tuning, (Computed, RatioTable, IntervalPattern, FrequencyTable, Tuning)
    )
    for lookup in case.lookups:
        if lookup.outside:
            with pytest.raises(ValueError, match='outside'):
                tuning(int(lookup.note))
        else:
            check_number(tuning(int(lookup.note)), lookup.exact, lookup.approx)
    if case.as_ratios is not None:
        assert isinstance(tuning, Computed)
        assert tuning.as_ratios().model_dump(mode='json') == case.as_ratios
    if isinstance(definition, TuningScore):
        assert parse_score(score_toml(definition)) == definition


@pytest.mark.parametrize('case', INVALID, ids=lambda c: c.id)
def test_invalid_definitions_are_rejected(case: DefinitionCase) -> None:
    with pytest.raises(ValueError):
        MODELS[case.model].model_validate(
            case.input, context={'portable': case.decision is None}
        )


@pytest.mark.parametrize('case', EXPRESSIONS, ids=lambda c: c.text)
def test_expression_results_preserve_exactness(case: ExpressionCase) -> None:
    if case.rejected:
        with pytest.raises(ValueError):
            evaluate(case.text)
    else:
        check_number(evaluate(case.text), case.exact, case.approx)


@pytest.mark.parametrize('text', DATA['invalid_expressions'])
def test_invalid_expressions_are_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        evaluate(text)


@pytest.mark.parametrize('case', BUDGETS, ids=lambda c: c.id)
def test_expression_budget_boundaries(case: BudgetCase) -> None:
    match case.operation:
        case 'pad_right':
            text = case.text.ljust(case.count)
        case 'parentheses':
            text = '(' * case.count + case.text + ')' * case.count
        case 'unary_plus':
            text = '+' * case.count + case.text
    if case.rejected:
        with pytest.raises(ValueError):
            evaluate(text)
    else:
        check_number(evaluate(text), case.exact, case.approx)


def prepare_table(case: PreparationCase) -> None:
    if case.model == 'computed':
        Computed(notes_per_octave=case.count, octave_ratio='1').as_ratios()
    else:
        MODELS[case.model].model_validate({case.model: ['1'] * case.count})


def check_number(
    value: Fraction | int | float, exact: str | None, approx: float | None
) -> None:
    assert (exact is None) != (approx is None)
    if exact is not None:
        assert isinstance(value, Fraction | int) and not isinstance(value, bool)
        assert value == Fraction(exact)
    else:
        assert isinstance(value, float)
        assert value == pytest.approx(
            approx,
            rel=DATA['relative_tolerance'],
            abs=0.0 if approx == 0.0 else DATA['absolute_tolerance'],
        )
