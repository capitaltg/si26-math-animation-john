import json
from dataclasses import dataclass

from pydantic import ValidationError

from app.meta.dsl.animation import AnimationDocument, CompiledAnimation, compile_animation_document
from app.meta.dsl.expression import ExpressionNode, compile_expression
from app.meta.dsl.guard import GuardDocument, compile_guard
from app.meta.dsl.params import ParamsDocument, TemplateParamsBase, compile_template_params
from app.pipeline.grounding import check_params_grounded


@dataclass(frozen=True)
class CompiledDraft:
    params_cls: type[TemplateParamsBase]
    compiled_animation: CompiledAnimation
    answer_expression: ExpressionNode
    known_fields: frozenset[str]


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
    return CompiledDraft(
        params_cls=params_cls,
        compiled_animation=compiled_animation,
        answer_expression=answer_expression,
        known_fields=known_fields,
    )


@dataclass(frozen=True)
class FixtureCheckResult:
    fixture_id: str
    passed: bool
    detail: str


def validate_fixture(fixture, compiled: CompiledDraft, source_excerpt: str | None) -> FixtureCheckResult:
    params_data = json.loads(fixture.params_json)
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
        )

    if actual_outcome == "accept" and fixture.kind == "positive" and source_excerpt is not None:
        ungrounded = check_params_grounded(params, source_excerpt)
        if ungrounded:
            return FixtureCheckResult(
                fixture.id, False, f"not grounded in source: {', '.join(ungrounded)}",
            )

    return FixtureCheckResult(fixture.id, True, detail)
