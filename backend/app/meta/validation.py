import json
from dataclasses import dataclass

from pydantic import ValidationError

from app.meta.dsl.animation import AnimationDocument, CompiledAnimation, compile_animation_document
from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import ExpressionNode, compile_expression
from app.meta.dsl.guard import CompiledGuard, GuardDocument, compile_guard
from app.meta.dsl.params import ParamsDocument, TemplateParamsBase, compile_template_params
from app.pipeline.grounding import check_params_grounded


@dataclass(frozen=True)
class CompiledDraft:
    params_cls: type[TemplateParamsBase]
    compiled_animation: CompiledAnimation
    answer_expression: ExpressionNode
    known_fields: frozenset[str]
    compiled_guard: CompiledGuard


def compile_draft_documents(
    params_document: ParamsDocument,
    guard_document: GuardDocument,
    answer_expression: ExpressionNode,
    animation_document: AnimationDocument,
) -> CompiledDraft:
    known_fields = frozenset(field.name for field in params_document.fields)
    compiled_guard = compile_guard(guard_document, known_fields)
    params_cls = compile_template_params(params_document, compiled_guard)
    compile_expression(answer_expression, known_fields)
    compiled_animation = compile_animation_document(animation_document, known_fields)
    if (
        animation_document.animation_version == 2
        and answer_expression not in compiled_animation.visible_answer_expressions
    ):
        raise DslValidationError(
            "answer_not_displayed",
            "version 2 animations must display answer_expression "
            "with an answer-role expression_label",
        )
    return CompiledDraft(
        params_cls=params_cls,
        compiled_animation=compiled_animation,
        answer_expression=answer_expression,
        known_fields=known_fields,
        compiled_guard=compiled_guard,
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
