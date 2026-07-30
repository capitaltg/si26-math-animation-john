"""In-memory validation for proposed meta-template v3 candidates."""

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app.meta.draft_generation import DraftProposal
from app.meta.draft_hash import compute_artifact_hash
from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.scene_program import SceneProgramDocument
from app.meta.dsl.v3_common import CompileContext
from app.meta.preview_render import render_preview_and_probe
from app.meta.v3.compiler import compile_teaching_plan
from app.meta.v3.errors import V3Failure, V3ValidationError
from app.meta.v3.quality import validate_static_quality
from app.meta.v3.render_probe import validate_rendered_quality
from app.meta.validation import (
    FixtureCheckResult,
    compile_draft_documents,
    first_positive_values,
    require_all_fixtures_and_guard_coverage,
    validate_proposed_fixtures,
)
from app.meta.versions import DSL_COMPILER_VERSION, DYNAMIC_RENDERER_VERSION


@dataclass(frozen=True)
class ValidatedCandidate:
    proposal: DraftProposal
    scene_program: SceneProgramDocument
    validation_report: dict
    quality_report: dict
    preview_artifact_hash: str
    fixture_results: list[FixtureCheckResult]


def validate_candidate(
    proposal: DraftProposal,
    observations_by_id: dict,
    artifact_root: Path,
    compile_context: CompileContext,
) -> ValidatedCandidate:
    """Validate a candidate without opening or accepting a database session."""
    try:
        compiled = compile_draft_documents(
            proposal.params_document,
            proposal.guard_document,
            proposal.answer_expression,
            proposal.teaching_plan_document,
        )
    except (DslValidationError, ValidationError) as exc:
        raise _validation_failure(exc, "documents", "valid parameter, guard, answer, and teaching-plan documents") from exc

    fixture_results = validate_proposed_fixtures(
        proposal.fixtures, compiled, observations_by_id
    )
    require_all_fixtures_and_guard_coverage(fixture_results, compiled)

    try:
        scene_program = compile_teaching_plan(
            proposal.teaching_plan_document,
            proposal.answer_expression,
            compiled.known_fields,
            compile_context,
        )
    except (DslValidationError, ValidationError) as exc:
        raise _validation_failure(exc, "teaching_plan_document", "a compilable v3 teaching plan") from exc

    static_quality = validate_static_quality(proposal.teaching_plan_document, scene_program)
    static_quality.require_passed()

    preview_hash, probe = render_preview_and_probe(
        scene_program,
        compiled.known_fields,
        first_positive_values(proposal.fixtures),
        artifact_root,
    )
    rendered_quality = validate_rendered_quality(probe)
    rendered_quality.require_passed()

    validation_report = build_validation_report(
        compiled=compiled,
        fixture_results=fixture_results,
        preview_artifact_hash=preview_hash,
    )
    quality_report = merge_quality_reports(
        static_quality,
        rendered_quality,
        artifact_hash=compute_candidate_hash(proposal, scene_program),
    )
    return ValidatedCandidate(
        proposal=proposal,
        scene_program=scene_program,
        validation_report=validation_report,
        quality_report=quality_report,
        preview_artifact_hash=preview_hash,
        fixture_results=fixture_results,
    )


def build_validation_report(*, compiled, fixture_results, preview_artifact_hash: str) -> dict:
    coverage = sorted({
        index
        for result in fixture_results
        for index in result.failed_predicate_indexes
    })
    return {
        "passed": True,
        "fixture_results": [
            {"fixture_id": result.fixture_id, "passed": result.passed, "detail": result.detail}
            for result in fixture_results
        ],
        "preview_ok": True,
        "preview_artifact_hash": preview_artifact_hash,
        "compiler_version": DSL_COMPILER_VERSION,
        "renderer_version": DYNAMIC_RENDERER_VERSION,
        "negative_predicate_coverage": coverage,
        "known_fields": sorted(compiled.known_fields),
    }


def merge_quality_reports(static_quality, rendered_quality, *, artifact_hash: str) -> dict:
    static_payload = static_quality.model_payload()
    rendered_payload = rendered_quality.model_payload()
    return {
        "passed": static_payload["passed"] and rendered_payload["passed"],
        "checks": [*static_payload["checks"], *rendered_payload["checks"]],
        "artifact_hash": artifact_hash,
    }


def compute_candidate_hash(proposal: DraftProposal, scene_program: SceneProgramDocument) -> str:
    dsl_versions = {
        "params_version": proposal.params_document.params_version,
        "guard_version": proposal.guard_document.guard_version,
        "teaching_plan_version": proposal.teaching_plan_document.plan_version,
        "scene_version": scene_program.scene_version,
    }
    return compute_artifact_hash(
        params_document=proposal.params_document.model_dump(mode="json"),
        guard_document=proposal.guard_document.model_dump(mode="json"),
        answer_expression=proposal.answer_expression.model_dump(mode="json"),
        teaching_plan_document=proposal.teaching_plan_document.model_dump(mode="json"),
        scene_program_document=scene_program.model_dump(mode="json"),
        classifier_bullet=proposal.classifier_bullet,
        dsl_schema_versions=dsl_versions,
        compiler_version=DSL_COMPILER_VERSION,
        renderer_version=DYNAMIC_RENDERER_VERSION,
    )


def _validation_failure(exc: Exception, path: str, expected: str) -> V3ValidationError:
    code = getattr(exc, "code", "candidate_compile_failed")
    return V3ValidationError(V3Failure(
        code=code,
        path=path,
        expected=expected,
        observed=str(exc),
        hint="correct the candidate documents and regenerate",
    ))
