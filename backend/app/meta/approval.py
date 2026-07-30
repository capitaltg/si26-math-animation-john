"""Atomic publication of a reviewed draft as a live ``TemplateVersion``.

This is the core transaction of the approval gate. Every precondition is
checked (read-only) *before* anything is mutated; the draft is then claimed
with a conditional update so two concurrent approvals of the same draft cannot
both publish; the prior enabled version for the fingerprint is disabled before
the new one is inserted (so the partial unique index never sees two enabled
rows); and an approval review row is recorded — all inside one
``meta_session()`` transaction.

Follows two existing idioms in this codebase:
- ``jobs.evaluate_and_enqueue`` — treat an ``IntegrityError`` from a partial
  unique index as a lost race.
- ``drafts.supersede_and_refine`` — flip the old row's status before inserting
  the new one so the unique index is never transiently violated.
"""

import json
import re
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.meta.db import meta_session
from app.meta.drafts import record_review
from app.meta.models import (
    DRAFT_APPROVED,
    DRAFT_PENDING_REVIEW,
    TEMPLATE_VERSION_DISABLED,
    TEMPLATE_VERSION_ENABLED,
    TEMPLATE_VERSION_REVOKED,
    TemplateDraft,
    TemplateDraftFixture,
    TemplateVersion,
)
from app.meta.versions import DSL_COMPILER_VERSION, DYNAMIC_RENDERER_VERSION

_TEMPLATE_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")


class ApprovalError(Exception):
    """Base class for all approval failures."""


class DraftNotFoundError(ApprovalError):
    """The draft id does not exist (maps to HTTP 404)."""


class DraftNotApprovableError(ApprovalError):
    """The draft is not in ``pending_review`` (maps to HTTP 409)."""


class ApprovalPreconditionError(ApprovalError):
    """A validation/confirmation precondition is unmet (maps to HTTP 422)."""


class RevokedConflictError(ApprovalError):
    """This fingerprint has a revoked live version (maps to HTTP 409)."""


class TemplateNameConflictError(ApprovalError):
    """``template_name`` is invalid or already taken (maps to HTTP 409)."""


class ApprovalConflictError(ApprovalError):
    """Lost a race with a concurrent approval (maps to HTTP 409)."""


def approve_draft_service(
    draft_id: str,
    template_name: str,
    reviewer_label: str,
    math_semantics_confirmed: bool,
) -> TemplateVersion:
    settings = get_settings()
    now = datetime.now(timezone.utc)

    try:
        with meta_session() as session:
            draft = session.get(TemplateDraft, draft_id)

            # --- Preconditions (checked in order, before any mutation) -----
            # 1. Draft exists and is pending review.
            if draft is None:
                raise DraftNotFoundError(f"Unknown draft {draft_id}")
            if draft.status != DRAFT_PENDING_REVIEW:
                raise DraftNotApprovableError(
                    f"Draft {draft_id} is not approvable in status {draft.status}"
                )

            # 2. The reviewer confirmed the mathematical semantics.
            if math_semantics_confirmed is not True:
                raise ApprovalPreconditionError(
                    "Mathematical-semantics confirmation is required for approval"
                )

            # 3. A validation report exists and passed.
            report = (
                json.loads(draft.validation_report_json)
                if draft.validation_report_json
                else None
            )
            if not report or report.get("passed") is not True:
                raise ApprovalPreconditionError(
                    "Draft has no passing validation report"
                )

            # 4. The report validated the exact artifact currently on the draft.
            if report.get("artifact_hash") != draft.artifact_hash:
                raise ApprovalPreconditionError(
                    "Validation report is stale: artifact hash mismatch"
                )

            # 5. The report ran against the active validation runtime.
            if (
                report.get("compiler_version") != DSL_COMPILER_VERSION
                or report.get("renderer_version") != DYNAMIC_RENDERER_VERSION
            ):
                raise ApprovalPreconditionError(
                    "Validation report is stale: runtime version mismatch"
                )

            # 6. Every guard predicate has a negative witness.
            predicate_count = len(json.loads(draft.guard_document_json)["predicates"])
            if report.get("negative_predicate_coverage") != list(range(predicate_count)):
                raise ApprovalPreconditionError(
                    "Validation report lacks complete negative-predicate coverage"
                )

            # 7. Enough real, human-confirmed positive fixtures.
            verified_fixtures = session.execute(
                select(func.count())
                .select_from(TemplateDraftFixture)
                .where(
                    TemplateDraftFixture.draft_id == draft.id,
                    TemplateDraftFixture.kind == "positive",
                    TemplateDraftFixture.observation_id.isnot(None),
                    TemplateDraftFixture.expected_result_json.isnot(None),
                    TemplateDraftFixture.structural_check_passed.is_(True),
                )
            ).scalar_one()
            if verified_fixtures < settings.meta_required_fixture_count:
                raise ApprovalPreconditionError(
                    "Draft has too few verified real fixtures to publish"
                )

            # 8. No revoked live version for this fingerprint.
            revoked = session.execute(
                select(func.count())
                .select_from(TemplateVersion)
                .where(
                    TemplateVersion.fingerprint_key == draft.fingerprint_key,
                    TemplateVersion.status == TEMPLATE_VERSION_REVOKED,
                )
            ).scalar_one()
            if revoked:
                raise RevokedConflictError(
                    f"Fingerprint {draft.fingerprint_key} has a revoked live version"
                )

            # 9. template_name is a valid slug and not owned by a different
            #    fingerprint's enabled version.
            if not _TEMPLATE_NAME_RE.fullmatch(template_name):
                raise TemplateNameConflictError(
                    f"Invalid template name {template_name!r}"
                )
            name_collision = session.execute(
                select(func.count())
                .select_from(TemplateVersion)
                .where(
                    TemplateVersion.template_name == template_name,
                    TemplateVersion.status == TEMPLATE_VERSION_ENABLED,
                    TemplateVersion.fingerprint_key != draft.fingerprint_key,
                )
            ).scalar_one()
            if name_collision:
                raise TemplateNameConflictError(
                    f"Template name {template_name!r} is already in use"
                )

            # --- Transaction (mutations begin here) ------------------------
            # 1. Claim the draft with a conditional update. A zero row count
            #    means a concurrent request already claimed it; bail out before
            #    touching any version rows.
            claimed = session.execute(
                update(TemplateDraft)
                .where(
                    TemplateDraft.id == draft.id,
                    TemplateDraft.status == DRAFT_PENDING_REVIEW,
                )
                .values(status=DRAFT_APPROVED, updated_at=now)
            )
            if claimed.rowcount != 1:
                raise ApprovalConflictError(
                    "draft approval was claimed by another request"
                )

            # 2. Disable any prior enabled version for this fingerprint before
            #    inserting the new one, so the partial unique index never sees
            #    two enabled rows at once.
            session.execute(
                update(TemplateVersion)
                .where(
                    TemplateVersion.fingerprint_key == draft.fingerprint_key,
                    TemplateVersion.status == TEMPLATE_VERSION_ENABLED,
                )
                .values(status=TEMPLATE_VERSION_DISABLED, updated_at=now)
            )

            # 3. Insert the new enabled version. An IntegrityError from the
            #    partial unique indexes means a concurrent approval beat us.
            version = TemplateVersion(
                id=uuid4().hex,
                fingerprint_key=draft.fingerprint_key,
                template_name=template_name,
                draft_id=draft.id,
                artifact_hash=draft.artifact_hash,
                status=TEMPLATE_VERSION_ENABLED,
                created_at=now,
                updated_at=now,
            )
            session.add(version)
            session.flush()

            # 4. Record the durable approval decision.
            record_review(
                session,
                new_id=uuid4().hex,
                draft_id=draft.id,
                decision="approve",
                reviewer_label=reviewer_label,
                feedback=None,
                math_semantics_confirmed=True,
                now=now,
            )
    except IntegrityError as exc:
        # meta_session already rolled back before re-raising; only now is it
        # safe to translate the lost race into our conflict error.
        raise ApprovalConflictError(
            "template version publication lost a race"
        ) from exc

    return version
