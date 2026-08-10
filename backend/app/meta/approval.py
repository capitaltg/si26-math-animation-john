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

from sqlalchemy import func, or_, select, update
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
    GenerationJob,
    TemplateDraft,
    TemplateDraftFixture,
    TemplateVersion,
)
from app.meta.versions import DSL_COMPILER_VERSION, DYNAMIC_RENDERER_VERSION
from app.models.scene import TemplateName

_TEMPLATE_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")

#: Names owned by static (compiled-in) templates. A dynamic template cannot be
#: published under any of these: classification.py resolves static names first,
#: so a colliding dynamic version would be silently shadowed and never
#: selectable. Reserved at approval time to keep the invariant one-way and
#: cheap to check.
_STATIC_TEMPLATE_NAMES = frozenset(member.value for member in TemplateName)


def _same_owner(owner_session_id: str | None):
    """Match versions belonging to exactly this owner.

    ``IS NULL`` rather than ``= NULL`` for the shared case, so the shared scope
    is a real scope rather than a comparison that matches nothing.
    """
    if owner_session_id is None:
        return TemplateVersion.owner_session_id.is_(None)
    return TemplateVersion.owner_session_id == owner_session_id


def _name_is_reserved(session, template_name: str, owner_session_id: str | None) -> bool:
    """Whether publishing under this name would collide inside someone's snapshot.

    The invariant a snapshot depends on: for any session S, the shared versions
    plus S's own private versions must have unique template names. Anything else
    puts two identical keys into one dict, where query order silently decides
    which template the name resolves to.

    That makes the check asymmetric:

    - publishing privately collides with a shared name (both are in *our* own
      snapshot) or with one of our own names;
    - publishing shared collides with another shared name, or with a name *any*
      session holds privately, since that session's snapshot would then hold two.

    Two different teachers may still choose the same private name: neither can
    see the other, so no single snapshot contains both.
    """
    scope = (
        # Sharing: every private holder of this name is a conflict.
        TemplateVersion.id.isnot(None)
        if owner_session_id is None
        else or_(
            TemplateVersion.owner_session_id.is_(None),
            TemplateVersion.owner_session_id == owner_session_id,
        )
    )
    taken = session.execute(
        select(func.count())
        .select_from(TemplateVersion)
        .where(
            TemplateVersion.template_name == template_name,
            TemplateVersion.status == TEMPLATE_VERSION_ENABLED,
            scope,
        )
    ).scalar_one()
    return bool(taken)


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


def _required_fixture_count(session, draft: TemplateDraft, owner_session_id: str | None) -> int:
    """How many verified real fixtures this approval demands.

    A shared version always demands the configured count. A session-scoped one
    demands a fixture per real example the draft was actually built from, capped
    at the configured count: a teacher who hit one novel problem cannot produce
    five examples of it, and holding them to evidence that cannot exist would
    make private approval impossible.

    Read from the job's frozen ``trigger_observation_ids`` rather than counting
    the fingerprint's observations live, so excluding an observation after
    generation can never lower the bar a draft is held to.
    """
    configured = get_settings().meta_required_fixture_count
    if owner_session_id is None:
        return configured
    job = session.get(GenerationJob, draft.job_id)
    built_from = len(json.loads(job.trigger_observation_ids)) if job else 0
    return min(configured, max(1, built_from))


def approve_draft_service(
    draft_id: str,
    template_name: str,
    reviewer_label: str,
    math_semantics_confirmed: bool,
    owner_session_id: str | None = None,
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

            # 5. A pedagogical quality report exists and passed.
            quality = (
                json.loads(draft.quality_report_json)
                if draft.quality_report_json
                else None
            )
            if not quality or quality.get("passed") is not True:
                raise ApprovalPreconditionError(
                    "Draft has no passing pedagogical quality report"
                )
            if quality.get("artifact_hash") != draft.artifact_hash:
                raise ApprovalPreconditionError(
                    "Quality report is stale: artifact hash mismatch"
                )

            # 6. The report ran against the active validation runtime.
            if (
                report.get("compiler_version") != DSL_COMPILER_VERSION
                or report.get("renderer_version") != DYNAMIC_RENDERER_VERSION
            ):
                raise ApprovalPreconditionError(
                    "Validation report is stale: runtime version mismatch"
                )

            # 7. Every guard predicate has a negative witness.
            predicate_count = len(json.loads(draft.guard_document_json)["predicates"])
            if report.get("negative_predicate_coverage") != list(range(predicate_count)):
                raise ApprovalPreconditionError(
                    "Validation report lacks complete negative-predicate coverage"
                )

            # 8. Enough real, human-confirmed positive fixtures.
            verified_fixtures = session.execute(
                select(func.count(func.distinct(TemplateDraftFixture.observation_id)))
                .select_from(TemplateDraftFixture)
                .where(
                    TemplateDraftFixture.draft_id == draft.id,
                    TemplateDraftFixture.kind == "positive",
                    TemplateDraftFixture.observation_id.isnot(None),
                    TemplateDraftFixture.expected_result_json.isnot(None),
                    TemplateDraftFixture.structural_check_passed.is_(True),
                )
            ).scalar_one()
            if verified_fixtures < _required_fixture_count(session, draft, owner_session_id):
                raise ApprovalPreconditionError(
                    "Draft has too few verified real fixtures to publish"
                )

            # 9. No revoked live version for this fingerprint.
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

            # 10. template_name is a valid slug and not owned by a different
            #    fingerprint's enabled version.
            if not _TEMPLATE_NAME_RE.fullmatch(template_name):
                raise TemplateNameConflictError(
                    f"Invalid template name {template_name!r}"
                )
            # A static (compiled-in) template already owns this name. The
            # classifier resolves static names first, so publishing a dynamic
            # version under a static name would be silently shadowed — never
            # selectable. Reject at approval time so the collision cannot
            # enter the DB.
            if template_name in _STATIC_TEMPLATE_NAMES:
                raise TemplateNameConflictError(
                    f"Template name {template_name!r} is reserved by a static template"
                )
            # Scoped so that no session can end up seeing two live templates
            # under one name; see _name_is_reserved for why this is asymmetric.
            # Re-publishing the same fingerprint under its existing name is a
            # replacement, not a collision, so it is excluded first.
            replaces_own = session.execute(
                select(func.count())
                .select_from(TemplateVersion)
                .where(
                    TemplateVersion.template_name == template_name,
                    TemplateVersion.status == TEMPLATE_VERSION_ENABLED,
                    TemplateVersion.fingerprint_key == draft.fingerprint_key,
                    _same_owner(owner_session_id),
                )
            ).scalar_one()
            if not replaces_own and _name_is_reserved(
                session, template_name, owner_session_id
            ):
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

            # 2. Disable this owner's prior enabled version for this fingerprint
            #    before inserting the new one, so the partial unique index never
            #    sees two enabled rows at once. Scoped to the same owner: another
            #    session's private version, and the shared one, are not ours to
            #    disable.
            session.execute(
                update(TemplateVersion)
                .where(
                    TemplateVersion.fingerprint_key == draft.fingerprint_key,
                    TemplateVersion.status == TEMPLATE_VERSION_ENABLED,
                    _same_owner(owner_session_id),
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
                owner_session_id=owner_session_id,
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
