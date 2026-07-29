import json
from datetime import datetime
from pathlib import Path

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.meta.dsl.animation import AnimationDocument
from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import ExpressionNode
from app.meta.dsl.guard import GuardDocument
from app.meta.dsl.params import ParamsDocument
from app.meta.models import DRAFT_FAILED_VALIDATION, DRAFT_PENDING_REVIEW, FallbackObservation, TemplateDraft, TemplateDraftFixture
from app.meta.preview_render import render_and_store_preview
from app.meta.validation import compile_draft_documents, validate_fixture
from app.meta.versions import DSL_COMPILER_VERSION, DYNAMIC_RENDERER_VERSION

_ExpressionAdapter = TypeAdapter(ExpressionNode)


def persist_validation(
    session: Session,
    draft: TemplateDraft,
    observations_by_id: dict[str, FallbackObservation],
    now: datetime,
    artifact_root: Path,
) -> bool:
    try:
        params_document = ParamsDocument.model_validate_json(draft.params_document_json)
        guard_document = GuardDocument.model_validate_json(draft.guard_document_json)
        answer_expression = _ExpressionAdapter.validate_json(draft.answer_expression_json)
        animation_document = AnimationDocument.model_validate_json(draft.animation_document_json)
        compiled = compile_draft_documents(
            params_document, guard_document, answer_expression, animation_document
        )
    except (DslValidationError, ValidationError) as exc:
        _finish(
            draft, now, passed=False, compile_error=str(exc), fixture_results=[],
            preview_ok=False, preview_error=None, preview_hash=None,
            negative_predicate_coverage=set(),
        )
        return False

    fixtures = session.query(TemplateDraftFixture).filter_by(draft_id=draft.id).all()
    fixture_results = []
    all_passed = True
    positive_params_for_preview = None
    negative_predicate_coverage: set[int] = set()
    for fixture in fixtures:
        observation = observations_by_id.get(fixture.observation_id) if fixture.observation_id else None
        result = validate_fixture(
            fixture, compiled, observation.source_excerpt if observation else None
        )
        fixture.structural_check_passed = result.passed
        fixture.structural_check_detail = result.detail
        fixture_results.append({"fixture_id": result.fixture_id, "passed": result.passed, "detail": result.detail})
        negative_predicate_coverage |= result.failed_predicate_indexes
        if not result.passed:
            all_passed = False
        elif fixture.kind == "positive" and fixture.expected_outcome == "accept" and positive_params_for_preview is None:
            positive_params_for_preview = json.loads(fixture.params_json)

    if not all_passed:
        _finish(
            draft, now, passed=False, compile_error=None, fixture_results=fixture_results,
            preview_ok=False, preview_error=None, preview_hash=None,
            negative_predicate_coverage=negative_predicate_coverage,
        )
        return False

    all_predicate_indexes = set(range(len(guard_document.predicates)))
    if not all_predicate_indexes.issubset(negative_predicate_coverage):
        _finish(
            draft, now, passed=False, compile_error=None, fixture_results=fixture_results,
            preview_ok=False, preview_error=None, preview_hash=None,
            negative_predicate_coverage=negative_predicate_coverage,
        )
        return False

    if positive_params_for_preview is None:
        _finish(
            draft, now, passed=False, compile_error=None, fixture_results=fixture_results,
            preview_ok=False, preview_error="no accepted positive fixture available for preview",
            preview_hash=None, negative_predicate_coverage=negative_predicate_coverage,
        )
        return False

    try:
        preview_hash = render_and_store_preview(
            compiled.compiled_animation, compiled.known_fields, positive_params_for_preview, artifact_root,
        )
    except Exception as exc:
        _finish(
            draft, now, passed=False, compile_error=None, fixture_results=fixture_results,
            preview_ok=False, preview_error=str(exc), preview_hash=None,
            negative_predicate_coverage=negative_predicate_coverage,
        )
        return False

    _finish(
        draft, now, passed=True, compile_error=None, fixture_results=fixture_results,
        preview_ok=True, preview_error=None, preview_hash=preview_hash,
        negative_predicate_coverage=negative_predicate_coverage,
    )
    return True


def _finish(
    draft: TemplateDraft,
    now: datetime,
    *,
    passed: bool,
    compile_error: str | None,
    fixture_results: list[dict],
    preview_ok: bool,
    preview_error: str | None,
    preview_hash: str | None,
    negative_predicate_coverage: set[int],
) -> None:
    draft.status = DRAFT_PENDING_REVIEW if passed else DRAFT_FAILED_VALIDATION
    draft.validation_report_json = json.dumps({
        "passed": passed,
        "compile_error": compile_error,
        "fixture_results": fixture_results,
        "preview_ok": preview_ok,
        "preview_error": preview_error,
        "artifact_hash": draft.artifact_hash,
        "compiler_version": DSL_COMPILER_VERSION,
        "renderer_version": DYNAMIC_RENDERER_VERSION,
        "negative_predicate_coverage": sorted(negative_predicate_coverage),
    })
    draft.preview_artifact_hash = preview_hash
    draft.updated_at = now
