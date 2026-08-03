import json
from dataclasses import dataclass

from pydantic import ValidationError

from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import ExpressionNode, FieldContract, compile_expression
from app.meta.dsl.guard import CompiledGuard, GuardDocument, compile_guard
from app.meta.dsl.params import (
    ParamsDocument, TemplateParamsBase, compile_template_params, field_contract_for,
)
from app.pipeline.grounding import check_params_grounded


@dataclass(frozen=True)
class CompiledDraft:
    params_cls: type[TemplateParamsBase]
    answer_expression: ExpressionNode
    known_fields: frozenset[str]
    compiled_guard: CompiledGuard
    #: The same fields as `known_fields`, but carrying each one's shape so
    #: compilation can tell a scalar from an array of items. `known_fields` stays
    #: a plain name set for the validation report and grounding.
    field_contract: FieldContract = FieldContract()


def compile_draft_documents(
    params_document: ParamsDocument,
    guard_document: GuardDocument,
    answer_expression: ExpressionNode,
    teaching_plan_document,
) -> CompiledDraft:
    field_contract = field_contract_for(params_document)
    compiled_guard = compile_guard(guard_document, field_contract)
    params_cls = compile_template_params(params_document, compiled_guard)
    compile_expression(answer_expression, field_contract)
    return CompiledDraft(
        params_cls=params_cls,
        answer_expression=answer_expression,
        known_fields=field_contract.names,
        compiled_guard=compiled_guard,
        field_contract=field_contract,
    )


@dataclass(frozen=True)
class FixtureCheckResult:
    fixture_id: str
    passed: bool
    detail: str
    failed_predicate_indexes: frozenset[int] = frozenset()


def _guard_witness_indexes(fixture, compiled: CompiledDraft, params_data: dict) -> frozenset[int]:
    # For fixtures expected to reject, evaluate the guard directly against the
    # raw (un-coerced) params data, even when Pydantic already rejected the same
    # params on field bounds before ever reaching the guard. This is the only way
    # to distinguish a proven guard-predicate witness from a generic field-bound
    # rejection: a witness requires the guard itself to evaluate successfully and
    # report a failing predicate, not merely that Pydantic said "reject".
    if fixture.expected_outcome != "reject":
        return frozenset()
    try:
        guard_result = compiled.compiled_guard.check(params_data)
    except DslValidationError:
        return frozenset()
    return frozenset(r.index for r in guard_result.predicate_results if not r.passed)


def validate_fixture(fixture, compiled: CompiledDraft, source_excerpt: str | None) -> FixtureCheckResult:
    params_data = json.loads(fixture.params_json)
    failed_predicate_indexes = _guard_witness_indexes(fixture, compiled, params_data)
    try:
        params = compiled.params_cls.model_validate(params_data)
        actual_outcome = "accept"
        detail = "params validated and guard passed"
    except ValidationError as exc:
        actual_outcome = "reject"
        errors = exc.errors()
        detail = f"rejected: {errors[0]['msg']}" if errors else f"rejected: {exc}"
        params = None

    if actual_outcome != fixture.expected_outcome:
        return FixtureCheckResult(
            fixture.id, False,
            f"expected {fixture.expected_outcome}, got {actual_outcome} ({detail})",
            failed_predicate_indexes,
        )

    if actual_outcome == "accept" and fixture.kind == "positive" and source_excerpt is not None:
        ungrounded = check_params_grounded(params, source_excerpt)
        if ungrounded:
            return FixtureCheckResult(
                fixture.id, False, f"not grounded in source: {', '.join(ungrounded)}",
                failed_predicate_indexes,
            )

    return FixtureCheckResult(fixture.id, True, detail, failed_predicate_indexes)


@dataclass(frozen=True)
class _ProposedFixtureForValidation:
    id: str
    kind: str
    expected_outcome: str
    params_json: str


def validate_proposed_fixtures(fixtures, compiled: CompiledDraft, observations_by_id: dict) -> list[FixtureCheckResult]:
    """Run structural checks without materializing ``TemplateDraftFixture`` rows."""
    results = []
    for index, fixture in enumerate(fixtures):
        fixture_id = f"fixture-{index}"
        candidate_fixture = _ProposedFixtureForValidation(
            id=fixture_id,
            kind=fixture.kind,
            expected_outcome=fixture.expected_outcome,
            params_json=json.dumps(fixture.params),
        )
        observation = observations_by_id.get(fixture.observation_id) if fixture.observation_id else None
        results.append(validate_fixture(
            candidate_fixture,
            compiled,
            observation.source_excerpt if observation is not None else None,
        ))
    return results


def require_all_fixtures_and_guard_coverage(
    fixture_results: list[FixtureCheckResult], compiled: CompiledDraft
) -> None:
    failed = next((result for result in fixture_results if not result.passed), None)
    if failed is not None:
        raise _fixture_failure(
            "fixture_validation_failed",
            f"fixtures[{failed.fixture_id}]",
            "fixture behavior consistent with the proposed template",
            failed.detail,
            "correct the fixture or candidate documents and regenerate",
        )

    covered = {
        predicate_index
        for result in fixture_results
        for predicate_index in result.failed_predicate_indexes
    }
    expected = set(range(len(compiled.compiled_guard.document.predicates)))
    if expected - covered:
        missing = ", ".join(str(index) for index in sorted(expected - covered))
        raise _fixture_failure(
            "guard_predicate_coverage_incomplete",
            "guard_document.predicates",
            "a rejecting fixture witness for every guard predicate",
            f"missing predicate indexes: {missing}",
            "add negative fixtures that independently reject on each missing predicate",
        )


def first_positive_values(fixtures) -> dict:
    for fixture in fixtures:
        if fixture.kind == "positive" and fixture.expected_outcome == "accept":
            return fixture.params
    raise _fixture_failure(
        "missing_preview_fixture",
        "fixtures",
        "an accepted positive fixture for the preview",
        "no accepted positive fixture was proposed",
        "add a grounded positive fixture and regenerate",
    )


def _fixture_failure(code: str, path: str, expected: str, observed: str, hint: str):
    from app.meta.v3.errors import V3Failure, V3ValidationError

    return V3ValidationError(V3Failure(
        code=code,
        path=path,
        expected=expected,
        observed=observed,
        hint=hint,
    ))
