"""One-off audit. Prints a TSV of persisted template-draft fixtures whose
params fail the new (multiset-based) grounding check. Read-only. Delete
after the migration cleanup (Task 8).

Usage (from backend/):
    .venv/bin/python -m scripts.audit_grounding > audit.tsv

Fields (tab-separated):
    record_type <TAB> id <TAB> draft_fingerprint_key <TAB> ungrounded_tokens <TAB> source_excerpt_head

Why this only audits fixtures, not "observations" or a template registry
lookup by slug (contrary to the generic template this script started from):
this repo's persistence layer (``app.meta.models``) has no params-bearing
Observation -- ``FallbackObservation`` only ever carries a source excerpt,
grade level and observation kind, never params. The only persisted params
live on ``TemplateDraftFixture.params_json``. A fixture's params class is
also not resolved via ``app.templates.registry.get_template`` by a
"template_slug" string: draft fixtures are DSL-authored per draft, and their
params class is compiled fresh from the draft's own params/guard/answer
documents. ``app.meta.validation.compile_draft_documents`` already does
exactly that for production fixture validation, so this script reuses it
rather than reimplementing template resolution.
"""

import json
import sys

from pydantic import TypeAdapter, ValidationError

from app.meta.db import meta_session
from app.meta.dsl.expression import ExpressionNode
from app.meta.dsl.guard import GuardDocument
from app.meta.dsl.params import ParamsDocument
from app.meta.models import FallbackObservation, TemplateDraft, TemplateDraftFixture
from app.meta.validation import compile_draft_documents
from app.pipeline.grounding import check_params_grounded

_ExpressionAdapter = TypeAdapter(ExpressionNode)


def _write_row(record_type: str, record_id: str, fingerprint_key: str,
               ungrounded: list[str], source_excerpt: str) -> None:
    head = source_excerpt.replace("\t", " ").replace("\n", " ")[:120]
    sys.stdout.write(
        "\t".join([
            record_type,
            str(record_id),
            fingerprint_key or "",
            ",".join(ungrounded),
            head,
        ]) + "\n"
    )


def _params_cls_for_draft(draft: TemplateDraft):
    compiled = compile_draft_documents(
        params_document=ParamsDocument.model_validate_json(draft.params_document_json),
        guard_document=GuardDocument.model_validate_json(draft.guard_document_json),
        answer_expression=_ExpressionAdapter.validate_json(draft.answer_expression_json),
        teaching_plan_document=None,  # unused by compile_draft_documents
    )
    return compiled.params_cls


def _audit_fixtures(session) -> None:
    fixtures = (
        session.query(TemplateDraftFixture)
        .filter_by(kind="positive", expected_outcome="accept")
        .order_by(TemplateDraftFixture.id)
        .yield_per(200)
    )
    for fixture in fixtures:
        if not fixture.observation_id:
            continue
        observation = session.get(FallbackObservation, fixture.observation_id)
        excerpt = observation.source_excerpt if observation is not None else None
        if not excerpt:
            continue

        draft = session.get(TemplateDraft, fixture.draft_id)
        if draft is None:
            _write_row("fixture:missing-draft", fixture.id, "", ["missing-draft"], excerpt)
            continue

        try:
            params_cls = _params_cls_for_draft(draft)
        except Exception as exc:
            _write_row("fixture:draft-compile-error", fixture.id, draft.fingerprint_key,
                        [type(exc).__name__], excerpt)
            continue

        params_data = json.loads(fixture.params_json)
        try:
            params = params_cls.model_validate(params_data)
        except ValidationError as exc:
            _write_row("fixture:params-load-error", fixture.id, draft.fingerprint_key,
                        [type(exc).__name__], excerpt)
            continue

        ungrounded = check_params_grounded(params, excerpt)
        if ungrounded:
            _write_row("fixture", fixture.id, draft.fingerprint_key, ungrounded, excerpt)


def main() -> int:
    with meta_session() as session:
        _audit_fixtures(session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
