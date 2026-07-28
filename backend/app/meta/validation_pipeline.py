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
        _finish(draft, now, passed=False, compile_error=str(exc), fixture_results=[], preview_ok=False, preview_error=None, preview_hash=None)
        return False

    fixtures = session.query(TemplateDraftFixture).filter_by(draft_id=draft.id).all()
    fixture_results = []
    all_passed = True
    positive_params_for_preview = None
    for fixture in fixtures:
        observation = observations_by_id.get(fixture.observation_id) if fixture.observation_id else None
        result = validate_fixture(
            fixture, compiled, observation.source_excerpt if observation else None
        )
        fixture.structural_check_passed = result.passed
        fixture.structural_check_detail = result.detail
        fixture_results.append({"fixture_id": result.fixture_id, "passed": result.passed, "detail": result.detail})
        if not result.passed:
            all_passed = False
        elif fixture.expected_outcome == "accept" and positive_params_for_preview is None:
            positive_params_for_preview = json.loads(fixture.params_json)

    if not all_passed:
        _finish(draft, now, passed=False, compile_error=None, fixture_results=fixture_results, preview_ok=False, preview_error=None, preview_hash=None)
        return False

    if positive_params_for_preview is None:
        _finish(
            draft, now, passed=False, compile_error=None, fixture_results=fixture_results,
            preview_ok=False, preview_error="no accepted positive fixture available for preview",
            preview_hash=None,
        )
        return False

    try:
        preview_hash = render_and_store_preview(
            compiled.compiled_animation, compiled.known_fields, positive_params_for_preview, artifact_root,
        )
    except Exception as exc:
        _finish(draft, now, passed=False, compile_error=None, fixture_results=fixture_results, preview_ok=False, preview_error=str(exc), preview_hash=None)
        return False

    _finish(draft, now, passed=True, compile_error=None, fixture_results=fixture_results, preview_ok=True, preview_error=None, preview_hash=preview_hash)
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
) -> None:
    draft.status = DRAFT_PENDING_REVIEW if passed else DRAFT_FAILED_VALIDATION
    draft.validation_report_json = json.dumps({
        "passed": passed,
        "compile_error": compile_error,
        "fixture_results": fixture_results,
        "preview_ok": preview_ok,
        "preview_error": preview_error,
    })
    draft.preview_artifact_hash = preview_hash
    draft.updated_at = now
