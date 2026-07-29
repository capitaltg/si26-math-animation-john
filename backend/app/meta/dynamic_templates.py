"""Load enabled dynamic templates: snapshot, ref resolution, compiled-scene loading.

An "enabled" dynamic template is a `TemplateVersion` (compiled from an approved
`TemplateDraft`) whose status is `TEMPLATE_VERSION_ENABLED`. This module bridges
those DB rows to the same `(scene_cls, params_cls)` shape that
`app.templates.registry.get_template` returns for a static (enum) template.
"""

from dataclasses import dataclass

from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from app.meta.dsl.animation import AnimationDocument
from app.meta.dsl.expression import ExpressionNode
from app.meta.dsl.guard import GuardDocument
from app.meta.dsl.params import ParamsDocument
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


def load_enabled_snapshot(session: Session) -> EnabledSnapshot:
    """Load a point-in-time snapshot of all enabled dynamic template versions."""
    rows = (
        session.query(TemplateVersion, TemplateDraft.classifier_bullet)
        .join(TemplateDraft, TemplateVersion.draft_id == TemplateDraft.id)
        .filter(TemplateVersion.status == TEMPLATE_VERSION_ENABLED)
        .all()
    )
    entries = {
        version.template_name: DynamicSnapshotEntry(
            version_id=version.id,
            artifact_hash=version.artifact_hash,
            classifier_bullet=classifier_bullet,
        )
        for version, classifier_bullet in rows
    }
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
# changes. artifact_hash mismatches are a caller-tampering / stale-ref signal (see
# get_dynamic_template below), not a case this cache needs to invalidate on.
_DYNAMIC_TEMPLATE_CACHE: dict[str, tuple[type, type]] = {}


def get_dynamic_template(ref: TemplateRef) -> tuple[type, type]:
    """Compile (or fetch from cache) the (scene_cls, params_cls) pair for a ref.

    Opens its own meta_session rather than accepting one, mirroring
    app.templates.registry.get_template's session-free signature -- callers pass
    only the pinned TemplateRef, not a live DB session.
    """
    cached = _DYNAMIC_TEMPLATE_CACHE.get(ref.version_id)
    if cached is not None:
        return cached

    from app.meta.db import meta_session

    with meta_session() as session:
        version = session.get(TemplateVersion, ref.version_id)
        if version is None or version.template_name != ref.name:
            raise TemplateVersionMismatchError(
                f"No dynamic template version {ref.version_id!r} for {ref.name!r}"
            )
        if version.artifact_hash != ref.artifact_hash:
            raise TemplateArtifactMismatchError(
                f"TemplateRef for {ref.name!r} has artifact_hash {ref.artifact_hash!r}, "
                f"but template_versions row {ref.version_id!r} has {version.artifact_hash!r}"
            )
        draft = session.get(TemplateDraft, version.draft_id)
        params_document = ParamsDocument.model_validate_json(draft.params_document_json)
        guard_document = GuardDocument.model_validate_json(draft.guard_document_json)
        answer_expression = _ExpressionAdapter.validate_json(draft.answer_expression_json)
        animation_document = AnimationDocument.model_validate_json(draft.animation_document_json)
        compiled = compile_draft_documents(
            params_document, guard_document, answer_expression, animation_document
        )

    scene_cls = type(
        f"DynamicScene_{ref.version_id}",
        (DynamicTemplateScene,),
        {"compiled_animation": compiled.compiled_animation},
    )
    result = (scene_cls, compiled.params_cls)
    _DYNAMIC_TEMPLATE_CACHE[ref.version_id] = result
    return result
