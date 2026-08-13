from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.meta import db
from app.meta.dsl.expression import FieldRefNode
from app.meta.dsl.guard import GuardDocument, PositivePredicate
from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import CompileContext
from app.meta.models import (
    JOB_SUCCEEDED,
    TEMPLATE_VERSION_DISABLED,
    TEMPLATE_VERSION_ENABLED,
    TEMPLATE_VERSION_REVOKED,
    GenerationJob,
    TemplateDraft,
    TemplateVersion,
)
from app.meta.v3.compiler import compile_teaching_plan

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


_MEDIAN_FIELDS = [f"v{index}" for index in range(1, 8)]


def _median_teaching_plan():
    # The same "identify the median of seven ordered values" plan validated
    # end-to-end in tests/render/test_dynamic_render_worker.py -- it compiles to
    # a scene program with a "median_callout" relation targeting
    # values.item[3].bottom, the item-specific anchor the reuse test below
    # resolves for every parameter set.
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Identify the middle value in an ordered odd-sized set.",
        "primary_visual": {
            "kind": "ordered_values", "ref": "values",
            "values": [{"node": "field_ref", "field": name} for name in _MEDIAN_FIELDS],
        },
        "strategy": "pair_elimination",
        "beats": [
            {"id": "reveal_values", "kind": "reveal", "targets": [{"visual_ref": "values"}],
             "intent": "show the ordered values together"},
            {"id": "organize_pairs", "kind": "organize", "targets": [{"visual_ref": "values"}],
             "intent": "pair values from the outside inward"},
            {"id": "focus_middle", "kind": "focus",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "identify the unpaired middle value"},
            {"id": "show_answer", "kind": "conclude",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "state the median"},
        ],
        "variation_seed": "dynamic-templates-test",
    })


def _seed_draft_and_version(
    session,
    *,
    template_name="decimal_comparison_grid",
    status=TEMPLATE_VERSION_ENABLED,
    fingerprint_key="k1",
    owner=None,
):
    now = _now()
    # Built from real DSL document models (not hand-rolled dicts) so the fixture
    # can't silently drift from the actual schemas.
    params_document = ParamsDocument(
        params_version=1,
        fields=[
            IntegerFieldSpec(name=name, label=name.upper(), description="", minimum=1, maximum=100)
            for name in _MEDIAN_FIELDS
        ],
    )
    guard_document = GuardDocument(
        guard_version=1,
        predicates=[PositivePredicate(value=FieldRefNode(field="v1"))],
    )
    answer_expression = FieldRefNode(field="v4")
    teaching_plan_document = _median_teaching_plan()
    scene_program = compile_teaching_plan(
        teaching_plan_document,
        answer_expression,
        frozenset(_MEDIAN_FIELDS),
        CompileContext(concept_family="measurement", grade_band="3-5"),
    )

    job = GenerationJob(
        id=f"job-{uuid4().hex}",
        fingerprint_key=fingerprint_key,
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
        fingerprint_key=fingerprint_key,
        fingerprint_version=1,
        fingerprint_json="{}",
        revision=1,
        params_document_json=params_document.model_dump_json(),
        guard_document_json=guard_document.model_dump_json(),
        answer_expression_json=answer_expression.model_dump_json(),
        teaching_plan_json=teaching_plan_document.model_dump_json(),
        scene_program_json=scene_program.model_dump_json(),
        classifier_bullet=f"- {template_name}: a test dynamic template.",
        dsl_schema_versions_json='{"params": 1, "guard": 1, "teaching_plan": 3, "scene": 3}',
        artifact_hash="sha256:draftx",
        status="approved",
        created_at=now,
        updated_at=now,
    )
    session.add(draft)
    session.flush()
    version = TemplateVersion(
        id=f"tv-{uuid4().hex}",
        fingerprint_key=fingerprint_key,
        template_name=template_name,
        draft_id=draft.id,
        artifact_hash="sha256:versionx",
        status=status,
        owner_session_id=owner,
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
    assert scene_cls.scene_program is not None
    assert issubclass(params_cls, TemplateParamsBase)
    params = params_cls(v1=3, v2=5, v3=6, v4=8, v5=9, v6=12, v7=15)
    assert params.v4 == 8


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


def test_published_v3_template_resolves_layout_for_each_params_set(session):
    """Published layout resolves afresh for each params set.

    Different digit widths must still produce the item-specific
    ``values.item[3].bottom`` anchor; layout is never baked in at publication.
    """
    from app.meta.dynamic_scene import resolve_dynamic_scene
    from app.meta.dynamic_templates import get_dynamic_template, resolve_dynamic_ref

    _draft, version = _seed_draft_and_version(session, template_name="median_of_seven")
    ref = resolve_dynamic_ref(session, "median_of_seven", version.id)
    scene_cls, params_cls = get_dynamic_template(ref)

    def _resolve_for_test(params):
        # Delegates to the exact same resolution helper DynamicTemplateScene.construct()
        # calls, so this test exercises production resolution logic rather than a
        # parallel reimplementation of it.
        return resolve_dynamic_scene(scene_cls.scene_program, params.model_dump())

    first = _resolve_for_test(params_cls.model_validate(
        {"v1": 3, "v2": 5, "v3": 6, "v4": 8, "v5": 9, "v6": 12, "v7": 15}
    ))
    second = _resolve_for_test(params_cls.model_validate(
        {"v1": 10, "v2": 20, "v3": 30, "v4": 40, "v5": 50, "v6": 60, "v7": 70}
    ))

    assert first.relation("median_callout").target == first.anchor("values", "item", 3, "bottom")
    assert second.relation("median_callout").target == second.anchor("values", "item", 3, "bottom")

    # Prove the two params sets actually produce DIFFERENT geometry -- without
    # this, a resolver that ignored `values` entirely (or served baked-in/
    # fixture coordinates) would still pass both assertions above, since each
    # only compares a resolution against itself. The 1-digit vs 2-digit values
    # widen the rendered text differently, so real per-params-set re-resolution
    # must shift these anchors; item[0] has the largest digit-width delta.
    assert first.anchor("values", "item", 3, "bottom") != second.anchor("values", "item", 3, "bottom")
    assert first.anchor("values", "item", 0, "bottom") != second.anchor("values", "item", 0, "bottom")


# ------------------------------------------------ ownership-scoped snapshots


def test_snapshot_hides_another_sessions_private_version(session):
    from app.meta.dynamic_templates import load_enabled_snapshot

    _seed_draft_and_version(
        session, template_name="theirs", fingerprint_key="k-theirs", owner="session-b"
    )

    assert load_enabled_snapshot(session, owner_session_id="session-a").names() == frozenset()


def test_snapshot_shows_a_session_its_own_private_version(session):
    from app.meta.dynamic_templates import load_enabled_snapshot

    _seed_draft_and_version(
        session, template_name="mine", fingerprint_key="k-mine", owner="session-a"
    )

    assert load_enabled_snapshot(session, owner_session_id="session-a").names() == frozenset(
        {"mine"}
    )


def test_snapshot_shows_shared_versions_to_every_session(session):
    from app.meta.dynamic_templates import load_enabled_snapshot

    _seed_draft_and_version(
        session, template_name="everyones", fingerprint_key="k-shared", owner=None
    )

    assert load_enabled_snapshot(session, owner_session_id="session-a").names() == frozenset(
        {"everyones"}
    )
    assert load_enabled_snapshot(session).names() == frozenset({"everyones"})


def test_an_owned_version_wins_over_the_shared_one_for_its_fingerprint(session):
    """One fingerprint must offer one template, not two.

    A teacher who deliberately approved their own template for a problem shape
    should be offered theirs, not theirs *and* the shared default.
    """
    from app.meta.dynamic_templates import load_enabled_snapshot

    _seed_draft_and_version(
        session, template_name="shared_grid", fingerprint_key="k1", owner=None
    )
    _seed_draft_and_version(
        session, template_name="own_grid", fingerprint_key="k1", owner="session-a"
    )

    assert load_enabled_snapshot(session, owner_session_id="session-a").names() == frozenset(
        {"own_grid"}
    )
    assert load_enabled_snapshot(session, owner_session_id="session-b").names() == frozenset(
        {"shared_grid"}
    )


def test_an_owned_version_does_not_hide_shared_ones_for_other_fingerprints(session):
    from app.meta.dynamic_templates import load_enabled_snapshot

    _seed_draft_and_version(
        session, template_name="shared_other", fingerprint_key="k-other", owner=None
    )
    _seed_draft_and_version(
        session, template_name="own_grid", fingerprint_key="k1", owner="session-a"
    )

    assert load_enabled_snapshot(session, owner_session_id="session-a").names() == frozenset(
        {"shared_other", "own_grid"}
    )


def test_a_name_collision_resolves_to_the_callers_own_version(session):
    """Defence in depth for data the name checks did not prevent.

    approve_draft_service now refuses a private approval that takes a shared
    name, so this state should not arise. If it ever does -- rows written before
    that check existed -- the snapshot must not let query order decide which
    template a name resolves to. The caller's own wins, matching the fingerprint
    precedence rule.
    """
    from app.meta.dynamic_templates import load_enabled_snapshot

    _seed_draft_and_version(
        session, template_name="same_name", fingerprint_key="k-shared", owner=None
    )
    _seed_draft_and_version(
        session, template_name="same_name", fingerprint_key="k-own", owner="session-a"
    )

    snapshot = load_enabled_snapshot(session, owner_session_id="session-a")

    assert snapshot.names() == frozenset({"same_name"})
    own_version_id = (
        session.query(TemplateVersion)
        .filter_by(template_name="same_name", owner_session_id="session-a")
        .one()
        .id
    )
    assert snapshot.entry("same_name").version_id == own_version_id


def test_a_name_collision_resolves_the_same_way_whichever_row_comes_first(session):
    """The mirror of the test above, seeded in the opposite order.

    Without both, the assertion can pass on query order alone and prove nothing.
    """
    from app.meta.dynamic_templates import load_enabled_snapshot

    _seed_draft_and_version(
        session, template_name="same_name", fingerprint_key="k-own", owner="session-a"
    )
    _seed_draft_and_version(
        session, template_name="same_name", fingerprint_key="k-shared", owner=None
    )

    snapshot = load_enabled_snapshot(session, owner_session_id="session-a")

    own_version_id = (
        session.query(TemplateVersion)
        .filter_by(template_name="same_name", owner_session_id="session-a")
        .one()
        .id
    )
    assert snapshot.entry("same_name").version_id == own_version_id
