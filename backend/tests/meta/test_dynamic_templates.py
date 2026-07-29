from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.meta import db
from app.meta.dsl.animation import AnimationDocument, LabelNode
from app.meta.dsl.expression import FieldRefNode
from app.meta.dsl.guard import GuardDocument, PositivePredicate
from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument
from app.meta.models import (
    JOB_SUCCEEDED,
    TEMPLATE_VERSION_DISABLED,
    TEMPLATE_VERSION_ENABLED,
    TEMPLATE_VERSION_REVOKED,
    GenerationJob,
    TemplateDraft,
    TemplateVersion,
)

# Same local engine/session fixture pattern used across tests/meta/ (see
# test_approval.py, test_validation_pipeline.py, test_drafts.py, test_models.py) --
# there is no shared conftest.py in this directory, so each test module defines its
# own in-memory-per-tmp_path-file session fixture and monkeypatches db.get_engine
# so that any code under test which opens its own session via meta_session() reuses
# the same engine/database as the fixture-provided session.


@pytest.fixture
def engine(tmp_path, monkeypatch):
    eng = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: eng)
    db.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.close()


def _now():
    return datetime.now(timezone.utc)


def _seed_draft_and_version(session, *, template_name="decimal_comparison_grid", status=TEMPLATE_VERSION_ENABLED):
    now = _now()
    # Built from real DSL document models (not hand-rolled dicts) so the fixture
    # can't silently drift from the actual schemas -- LabelNode.text is a plain
    # `str` (not an ExpressionNode) and AnimationDocument forbids extra fields
    # (no top-level total_duration_seconds; that's computed by compile_animation_document).
    params_document = ParamsDocument(
        params_version=1,
        fields=[
            IntegerFieldSpec(name="a", label="A", description="", minimum=1, maximum=20),
            IntegerFieldSpec(name="b", label="B", description="", minimum=1, maximum=20),
        ],
    )
    guard_document = GuardDocument(
        guard_version=1,
        predicates=[PositivePredicate(value=FieldRefNode(field="a"))],
    )
    answer_expression = FieldRefNode(field="a")
    animation_document = AnimationDocument(root=LabelNode(text="a dynamic template", style="primary"))

    job = GenerationJob(
        id=f"job-{uuid4().hex}",
        fingerprint_key="k1",
        fingerprint_version=1,
        fingerprint_json="{}",
        trigger_observation_ids="[]",
        status=JOB_SUCCEEDED,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    session.flush()

    draft = TemplateDraft(
        id=f"draft-{uuid4().hex}",
        job_id=job.id,
        fingerprint_key="k1",
        fingerprint_version=1,
        fingerprint_json="{}",
        revision=1,
        params_document_json=params_document.model_dump_json(),
        guard_document_json=guard_document.model_dump_json(),
        answer_expression_json=answer_expression.model_dump_json(),
        animation_document_json=animation_document.model_dump_json(),
        classifier_bullet=f"- {template_name}: a test dynamic template.",
        dsl_schema_versions_json='{"params": 1, "guard": 1, "animation": 1}',
        artifact_hash="sha256:draftx",
        status="approved",
        created_at=now,
        updated_at=now,
    )
    session.add(draft)
    session.flush()
    version = TemplateVersion(
        id=f"tv-{uuid4().hex}",
        fingerprint_key="k1",
        template_name=template_name,
        draft_id=draft.id,
        artifact_hash="sha256:versionx",
        status=status,
        created_at=now,
        updated_at=now,
    )
    session.add(version)
    # commit (not just flush): get_dynamic_template opens its OWN session via
    # meta_session(), a different connection against the same monkeypatched engine,
    # so the seeded rows must be durably committed to be visible there.
    session.commit()
    return draft, version


def test_load_enabled_snapshot_includes_only_enabled_versions(session):
    from app.meta.dynamic_templates import load_enabled_snapshot

    _seed_draft_and_version(session, template_name="enabled_one", status=TEMPLATE_VERSION_ENABLED)
    _seed_draft_and_version(session, template_name="disabled_one", status=TEMPLATE_VERSION_DISABLED)
    _seed_draft_and_version(session, template_name="revoked_one", status=TEMPLATE_VERSION_REVOKED)

    snapshot = load_enabled_snapshot(session)

    assert snapshot.names() == frozenset({"enabled_one"})
    entry = snapshot.entry("enabled_one")
    assert entry.classifier_bullet == "- enabled_one: a test dynamic template."
    assert snapshot.entry("disabled_one") is None
    assert snapshot.entry("nonexistent") is None


def test_resolve_dynamic_ref_returns_a_template_ref_for_an_enabled_version(session):
    from app.meta.dynamic_templates import resolve_dynamic_ref

    _draft, version = _seed_draft_and_version(session, template_name="my_template")

    ref = resolve_dynamic_ref(session, "my_template", version.id)

    assert ref.name == "my_template"
    assert ref.version_id == version.id
    assert ref.artifact_hash == "sha256:versionx"


def test_resolve_dynamic_ref_accepts_a_disabled_but_not_revoked_version(session):
    from app.meta.dynamic_templates import resolve_dynamic_ref

    _draft, version = _seed_draft_and_version(
        session, template_name="my_template", status=TEMPLATE_VERSION_DISABLED
    )

    ref = resolve_dynamic_ref(session, "my_template", version.id)
    assert ref.version_id == version.id


def test_resolve_dynamic_ref_rejects_a_revoked_version(session):
    from app.models.scene import TemplateVersionMismatchError
    from app.meta.dynamic_templates import resolve_dynamic_ref

    _draft, version = _seed_draft_and_version(
        session, template_name="my_template", status=TEMPLATE_VERSION_REVOKED
    )

    with pytest.raises(TemplateVersionMismatchError):
        resolve_dynamic_ref(session, "my_template", version.id)


def test_resolve_dynamic_ref_rejects_a_nonexistent_version(session):
    from app.models.scene import TemplateVersionMismatchError
    from app.meta.dynamic_templates import resolve_dynamic_ref

    with pytest.raises(TemplateVersionMismatchError):
        resolve_dynamic_ref(session, "my_template", "ghost-version-id")


def test_resolve_dynamic_ref_rejects_a_version_id_belonging_to_a_different_name(session):
    from app.models.scene import TemplateVersionMismatchError
    from app.meta.dynamic_templates import resolve_dynamic_ref

    _draft, version = _seed_draft_and_version(session, template_name="my_template")

    with pytest.raises(TemplateVersionMismatchError):
        resolve_dynamic_ref(session, "some_other_name", version.id)


def test_get_dynamic_template_loads_a_scene_and_params_class(session):
    from app.meta.dynamic_templates import get_dynamic_template, resolve_dynamic_ref
    from app.meta.dsl.params import TemplateParamsBase
    from app.meta.dynamic_scene import DynamicTemplateScene

    _draft, version = _seed_draft_and_version(session, template_name="my_template")
    ref = resolve_dynamic_ref(session, "my_template", version.id)

    scene_cls, params_cls = get_dynamic_template(ref)

    assert issubclass(scene_cls, DynamicTemplateScene)
    assert scene_cls.compiled_animation is not None
    assert issubclass(params_cls, TemplateParamsBase)
    params = params_cls(a=3, b=4)
    assert params.a == 3


def test_get_dynamic_template_is_cached_by_version_and_hash(session):
    from app.meta.dynamic_templates import get_dynamic_template, resolve_dynamic_ref

    _draft, version = _seed_draft_and_version(session, template_name="my_template")
    ref = resolve_dynamic_ref(session, "my_template", version.id)

    first_scene_cls, first_params_cls = get_dynamic_template(ref)
    second_scene_cls, second_params_cls = get_dynamic_template(ref)

    assert first_scene_cls is second_scene_cls
    assert first_params_cls is second_params_cls


def test_get_dynamic_template_rejects_a_ref_with_a_mismatched_hash(session):
    from app.models.scene import TemplateArtifactMismatchError
    from app.meta.dynamic_templates import get_dynamic_template, resolve_dynamic_ref

    _draft, version = _seed_draft_and_version(session, template_name="my_template")
    ref = resolve_dynamic_ref(session, "my_template", version.id)
    tampered = ref.model_copy(update={"artifact_hash": "sha256:not-the-real-hash"})

    with pytest.raises(TemplateArtifactMismatchError):
        get_dynamic_template(tampered)


def test_get_dynamic_template_rejects_a_ref_after_its_version_is_revoked(session):
    from app.models.scene import TemplateVersionMismatchError
    from app.meta.dynamic_templates import get_dynamic_template, resolve_dynamic_ref

    _draft, version = _seed_draft_and_version(session, template_name="my_template")
    ref = resolve_dynamic_ref(session, "my_template", version.id)
    get_dynamic_template(ref)  # Populate the compilation cache before revocation.
    version.status = TEMPLATE_VERSION_REVOKED
    session.commit()

    with pytest.raises(TemplateVersionMismatchError):
        get_dynamic_template(ref)


def test_get_dynamic_template_rejects_a_tampered_hash_after_cache_is_populated(session):
    """A version_id already cached from a prior successful (correct-hash) call must
    NOT let a later call with a tampered artifact_hash bypass the hash check --
    the cache must not shadow the mismatch validation."""
    from app.models.scene import TemplateArtifactMismatchError
    from app.meta.dynamic_templates import get_dynamic_template, resolve_dynamic_ref

    _draft, version = _seed_draft_and_version(session, template_name="my_template")
    ref = resolve_dynamic_ref(session, "my_template", version.id)

    # Populate the cache with a correct, successful call first.
    get_dynamic_template(ref)

    tampered = ref.model_copy(update={"artifact_hash": "sha256:tampered"})

    with pytest.raises(TemplateArtifactMismatchError):
        get_dynamic_template(tampered)
