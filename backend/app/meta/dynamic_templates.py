"""Load enabled dynamic templates: snapshot, ref resolution, compiled-scene loading.

An "enabled" dynamic template is a `TemplateVersion` (compiled from an approved
`TemplateDraft`) whose status is `TEMPLATE_VERSION_ENABLED`. This module bridges
those DB rows to the same `(scene_cls, params_cls)` shape that
`app.templates.registry.get_template` returns for a static (enum) template.
"""

import logging
from dataclasses import dataclass

from pydantic import TypeAdapter
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.meta.dsl.expression import ExpressionNode
from app.meta.dsl.guard import GuardDocument
from app.meta.dsl.params import ParamsDocument
from app.meta.dsl.scene_program import SceneProgramDocument
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dynamic_scene import DynamicTemplateScene
from app.meta.models import (
    TEMPLATE_VERSION_ENABLED,
    TEMPLATE_VERSION_REVOKED,
    TemplateDraft,
    TemplateVersion,
)
from app.meta.validation import compile_draft_documents
from app.models.scene import (
    TemplateArtifactMismatchError,
    TemplateRef,
    TemplateVersionMismatchError,
)

logger = logging.getLogger(__name__)

# Same deserialization pattern as app/meta/drafts.py:_ExpressionAdapter and
# app/meta/validation_pipeline.py:_ExpressionAdapter -- ExpressionNode is a
# discriminated Union type alias, not a BaseModel, so it has no .model_validate_json
# of its own; TypeAdapter provides that.
_ExpressionAdapter = TypeAdapter(ExpressionNode)


@dataclass(frozen=True)
class DynamicSnapshotEntry:
    version_id: str
    artifact_hash: str
    classifier_bullet: str


@dataclass(frozen=True)
class EnabledSnapshot:
    """Frozen mapping-like view of the currently-enabled dynamic template versions."""

    _entries: dict[str, DynamicSnapshotEntry]

    def names(self) -> frozenset[str]:
        return frozenset(self._entries.keys())

    def entry(self, name: str) -> DynamicSnapshotEntry | None:
        return self._entries.get(name)


def load_enabled_snapshot(
    session: Session, owner_session_id: str | None = None
) -> EnabledSnapshot:
    """Load a point-in-time snapshot of the dynamic templates one session may use.

    That is every shared version (``owner_session_id IS NULL``) plus the
    versions this session approved for itself. Another session's private version
    is not included -- it is enabled, but not for this caller.

    When a session holds its own version for a fingerprint, the shared version
    for that same fingerprint is dropped: one problem shape must offer one
    template, and a teacher's deliberate approval outranks the shared default.
    """
    query = (
        session.query(TemplateVersion, TemplateDraft.classifier_bullet)
        .join(TemplateDraft, TemplateVersion.draft_id == TemplateDraft.id)
        .filter(TemplateVersion.status == TEMPLATE_VERSION_ENABLED)
    )
    if owner_session_id is None:
        query = query.filter(TemplateVersion.owner_session_id.is_(None))
    else:
        query = query.filter(
            or_(
                TemplateVersion.owner_session_id.is_(None),
                TemplateVersion.owner_session_id == owner_session_id,
            )
        )
    rows = query.all()

    owned_fingerprints = {
        version.fingerprint_key for version, _ in rows if version.owner_session_id is not None
    }
    visible = [
        (version, classifier_bullet)
        for version, classifier_bullet in rows
        if version.owner_session_id is not None
        or version.fingerprint_key not in owned_fingerprints
    ]

    # Shared first, then the caller's own, so an owned version always wins a
    # name collision rather than whichever row the query happened to return
    # last. approve_draft_service refuses to create such a collision in the
    # first place; this keeps the resolution deterministic for rows written
    # before that check existed, and for any future path that misses it.
    entries: dict[str, DynamicSnapshotEntry] = {}
    for owned in (False, True):
        for version, classifier_bullet in visible:
            if (version.owner_session_id is not None) is not owned:
                continue
            if owned and version.template_name in entries:
                logger.warning(
                    "Template name %r is held by both a shared and a private version; "
                    "resolving to the caller's own version %s",
                    version.template_name, version.id,
                )
            entries[version.template_name] = DynamicSnapshotEntry(
                version_id=version.id,
                artifact_hash=version.artifact_hash,
                classifier_bullet=classifier_bullet,
            )
    return EnabledSnapshot(_entries=entries)


def resolve_dynamic_ref(session: Session, name: str, version_id: str) -> TemplateRef:
    """Resolve a (name, version_id) pair into a pinned TemplateRef.

    Accepts any non-revoked version (enabled or disabled) so a Scene pinned to a
    version that has since been superseded (disabled) but not revoked can still
    be resolved and re-rendered -- only revocation (a hard "this version is no
    longer safe to load") blocks resolution.
    """
    version = session.get(TemplateVersion, version_id)
    if (
        version is None
        or version.template_name != name
        or version.status == TEMPLATE_VERSION_REVOKED
    ):
        raise TemplateVersionMismatchError(
            f"No loadable dynamic template version for {name!r} with version_id {version_id!r}"
        )
    return TemplateRef(name=name, version_id=version.id, artifact_hash=version.artifact_hash)


# Cache keyed by version_id: a TemplateVersion row is immutable once created (a new
# draft revision publishes a new TemplateVersion row, it never mutates an existing
# one), so the compiled (scene_cls, params_cls) pair for a given version_id never
# changes. This cache only ever short-circuits the expensive *compilation* work
# (params/guard/animation document parsing + compile_draft_documents) -- it must
# NOT be consulted before the artifact_hash on the ref has been checked against
# the live DB row, since a caller can present the same version_id together with a
# tampered/stale artifact_hash and that must always raise
# TemplateArtifactMismatchError, even for a version_id whose (correct-hash) result
# is already cached.
_DYNAMIC_TEMPLATE_CACHE: dict[str, tuple[type, type]] = {}


def get_dynamic_template(ref: TemplateRef) -> tuple[type, type]:
    """Validate a ref against the live DB row, then fetch (or compile) the
    (scene_cls, params_cls) pair for it.

    Opens its own meta_session rather than accepting one, mirroring
    app.templates.registry.get_template's session-free signature -- callers pass
    only the pinned TemplateRef, not a live DB session. The DB lookup and
    artifact_hash check always run, on every call (a single cheap session.get);
    only the compilation step below is skipped on a cache hit.
    """
    from app.meta.db import meta_session

    with meta_session() as session:
        version = session.get(TemplateVersion, ref.version_id)
        if (
            version is None
            or version.template_name != ref.name
            or version.status == TEMPLATE_VERSION_REVOKED
        ):
            raise TemplateVersionMismatchError(
                f"No dynamic template version {ref.version_id!r} for {ref.name!r}"
            )
        if version.artifact_hash != ref.artifact_hash:
            raise TemplateArtifactMismatchError(
                f"TemplateRef for {ref.name!r} has artifact_hash {ref.artifact_hash!r}, "
                f"but template_versions row {ref.version_id!r} has {version.artifact_hash!r}"
            )

        cached = _DYNAMIC_TEMPLATE_CACHE.get(ref.version_id)
        if cached is not None:
            return cached

        draft = session.get(TemplateDraft, version.draft_id)
        params_document = ParamsDocument.model_validate_json(draft.params_document_json)
        guard_document = GuardDocument.model_validate_json(draft.guard_document_json)
        answer_expression = _ExpressionAdapter.validate_json(draft.answer_expression_json)
        teaching_plan_document = TeachingPlanDocument.model_validate_json(draft.teaching_plan_json)
        scene_program = SceneProgramDocument.model_validate_json(draft.scene_program_json)
        compiled = compile_draft_documents(
            params_document, guard_document, answer_expression, teaching_plan_document
        )

    scene_cls = type(
        f"DynamicScene_{ref.version_id}",
        (DynamicTemplateScene,),
        {"scene_program": scene_program},
    )
    result = (scene_cls, compiled.params_cls)
    _DYNAMIC_TEMPLATE_CACHE[ref.version_id] = result
    return result
