"""Share a session-scoped template version with everyone.

The one thing the admin panel gains from teacher-owned templates. A teacher
approves a template for their own session under a relaxed evidence floor --
enough verified fixtures for the examples their draft was built from. Sharing it
is a different decision with a different bar, so this re-checks the full
configured floor rather than trusting the private approval.
"""

import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.meta.db import meta_session
from app.meta.models import (
    TEMPLATE_VERSION_ENABLED,
    TemplateDraftFixture,
    TemplateVersion,
)


class PromotionError(Exception):
    """Base class for every refusal to share a version."""


class VersionNotFoundError(PromotionError):
    """No such version (maps to HTTP 404)."""


class VersionNotPromotableError(PromotionError):
    """Already shared, or not enabled (maps to HTTP 409)."""


class PromotionEvidenceError(PromotionError):
    """Too little verified evidence to hold everyone to it (maps to HTTP 422)."""


class PromotionNameConflictError(PromotionError):
    """A shared template already holds this name (maps to HTTP 409)."""


def promote_version(version_id: str) -> TemplateVersion:
    now = datetime.now(timezone.utc)
    settings = get_settings()
    try:
        with meta_session() as session:
            version = session.get(TemplateVersion, version_id)
            if version is None:
                raise VersionNotFoundError(f"Unknown template version {version_id}")
            if version.status != TEMPLATE_VERSION_ENABLED:
                raise VersionNotPromotableError(
                    f"Template version {version_id} is not enabled"
                )
            if version.owner_session_id is None:
                raise VersionNotPromotableError(
                    f"Template version {version_id} is already shared"
                )

            # The full floor, not the relaxed one the private approval used.
            verified = session.execute(
                select(func.count(func.distinct(TemplateDraftFixture.observation_id)))
                .select_from(TemplateDraftFixture)
                .where(
                    TemplateDraftFixture.draft_id == version.draft_id,
                    TemplateDraftFixture.kind == "positive",
                    TemplateDraftFixture.observation_id.isnot(None),
                    TemplateDraftFixture.expected_result_json.isnot(None),
                    TemplateDraftFixture.structural_check_passed.is_(True),
                )
            ).scalar_one()
            if verified < settings.meta_required_fixture_count:
                raise PromotionEvidenceError(
                    "This template has too few verified real examples to share "
                    f"({verified} of {settings.meta_required_fixture_count})"
                )

            # Checked before the write as well as being enforced by the partial
            # unique index, so the refusal names the actual problem rather than
            # surfacing as a lost race.
            name_taken = session.execute(
                select(func.count())
                .select_from(TemplateVersion)
                .where(
                    TemplateVersion.template_name == version.template_name,
                    TemplateVersion.status == TEMPLATE_VERSION_ENABLED,
                    TemplateVersion.owner_session_id.is_(None),
                )
            ).scalar_one()
            if name_taken:
                raise PromotionNameConflictError(
                    f"A shared template is already called {version.template_name!r}"
                )

            fingerprint_taken = session.execute(
                select(func.count())
                .select_from(TemplateVersion)
                .where(
                    TemplateVersion.fingerprint_key == version.fingerprint_key,
                    TemplateVersion.status == TEMPLATE_VERSION_ENABLED,
                    TemplateVersion.owner_session_id.is_(None),
                )
            ).scalar_one()
            if fingerprint_taken:
                raise PromotionNameConflictError(
                    "A shared template already covers this kind of problem"
                )

            version.owner_session_id = None
            version.updated_at = now
            session.flush()
            return version
    except IntegrityError as exc:
        raise PromotionNameConflictError(
            "sharing this template lost a race with another change"
        ) from exc


def enabled_versions() -> list[dict]:
    """Every enabled version with its owner, for the admin library listing."""
    with meta_session() as session:
        rows = (
            session.query(TemplateVersion)
            .filter(TemplateVersion.status == TEMPLATE_VERSION_ENABLED)
            .order_by(TemplateVersion.created_at.desc())
            .all()
        )
        return [
            {
                "id": row.id,
                "template_name": row.template_name,
                "fingerprint_key": row.fingerprint_key,
                "owner_session_id": row.owner_session_id,
                "created_at": row.created_at,
            }
            for row in rows
        ]
