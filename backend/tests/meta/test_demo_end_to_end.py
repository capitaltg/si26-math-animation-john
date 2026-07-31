"""End-to-end coverage of the live v3 meta-template demo runbook, with Bedrock
the only thing mocked.

This walks the exact sequence a presenter performs (docs/meta-template-demo.md)
for both demo lessons: seed an unsupported-shape observation, let the worker
generate a bounded v3 teaching plan and validate it privately, review the
draft's teaching beats and quality evidence, confirm the known answer on the
grounded fixture, approve and publish, then reuse the published template on a
second problem and render a real MP4.

Both demo lessons are literal ``TeachingPlanDocument`` payloads (no v1/v2
animation documents anywhere): a median-of-seven lesson driven by
``pair_elimination`` over ``ordered_values``, and a rectangle-perimeter lesson
driven by ``boundary_trace`` over ``rectangle_measurement``.

``rendered_median`` / ``rendered_perimeter`` carry the evidence this module and
``tests/meta/test_v3_demo_quality.py`` assert against.
``build_demo_quality_report`` is the single place probe-manifest evidence is
mapped onto the fields those acceptance contracts read.
"""

import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from app.config import get_settings
from app.meta import db, models
from app.meta.db import meta_session
from app.meta.dsl.expression import ExpressionNode, compile_expression
from app.meta.dsl.scene_program import SceneProgramDocument
from app.meta.dynamic_scene import resolve_dynamic_scene
from app.meta.dynamic_templates import (
    get_dynamic_template,
    load_enabled_snapshot,
    resolve_dynamic_ref,
)
from app.meta.fingerprint import Fingerprint
from app.meta.generation_pipeline import run_generation_job
from app.meta.ingest import record_unsupported_shape
from app.meta.preview_render import render_preview_and_probe
from app.meta.v3.quality import DIMENSION_TARGET_PARTS
# ``_normalized_distance`` is imported deliberately: it is the exact function
# production's ``check_relation_alignment`` uses to decide whether a callout tip
# sits on its semantic anchor. Reusing it (rather than re-deriving the distance
# here) keeps the demo contract measuring alignment the way the shipped quality
# gate measures it, instead of adding a second quality algorithm to the tests.
from app.meta.v3.render_probe import ANCHOR_TOLERANCE, _normalized_distance
from app.models.scene import TemplateName
from app.pipeline.classification import ClassificationResult, TemplateOption
from app.render.full_render import render_scene_to_mp4

_EXPRESSION = TypeAdapter(ExpressionNode)


@pytest.fixture
def client(tmp_path, monkeypatch):
    meta_db = tmp_path / "meta.db"
    engine = db.make_engine(meta_db)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    # The render steps run in subprocesses that open their own meta_session from
    # settings, so they must be pointed at the same on-disk DB as this process.
    monkeypatch.setenv("META_DB_PATH", str(meta_db))
    monkeypatch.setenv("META_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("META_TEMPLATES_ENABLED", "1")
    monkeypatch.setenv("META_CODEGEN_ENABLED", "1")
    monkeypatch.setenv("META_APPROVAL_ENABLED", "1")
    # Match the runbook's demo tuning: one observation seeds a draft, one
    # human-verified real fixture is enough to publish.
    monkeypatch.setenv("FINGERPRINT_OBSERVATION_THRESHOLD", "1")
    monkeypatch.setenv("META_REQUIRED_FIXTURE_COUNT", "1")
    monkeypatch.setenv("META_REVIEWER_TOKEN", "test-token")
    get_settings.cache_clear()
    from app.main import create_app

    yield TestClient(create_app(), headers={"Authorization": "Bearer test-token"})
    get_settings.cache_clear()


# --------------------------------------------------------------- demo lessons


@dataclass(frozen=True)
class DemoLesson:
    """One demo slide pair: what Bedrock proposes and what the reviewer knows."""

    template_name: str
    source_excerpt: str
    fingerprint: Fingerprint
    params_document: dict
    guard_document: dict
    answer_expression: dict
    teaching_plan: dict
    classifier_bullet: str
    primary_visual_ref: str
    expected_beat_ids: list[str]
    verified_params: dict
    verified_answer: int
    negative_params: list[dict]
    second_params: dict
    second_answer: int

    @property
    def known_fields(self) -> frozenset[str]:
        return frozenset(field["name"] for field in self.params_document["fields"])

    @property
    def derive_beat_id(self) -> str | None:
        """Id of the beat that derives the answer, if the lesson teaches one."""
        return next(
            (beat["id"] for beat in self.teaching_plan["beats"] if beat["kind"] == "derive"),
            None,
        )


def _median_values(values):
    return {f"v{index}": value for index, value in enumerate(values, start=1)}


# Seven ordered values, so the unpaired middle item is values.item[3] -- the
# item pair_elimination focuses and anchors its "median" callout to.
MEDIAN_LESSON = DemoLesson(
    template_name="median_of_seven",
    # Slide 3 of eval/fixtures/meta_template_unsupported_shapes_deck.pptx, verbatim.
    source_excerpt="What is the median of 3, 5, 6, 8, 9, 12, and 15?",
    fingerprint=Fingerprint(
        fingerprint_version=1, operation_family="measure", representation_family="set",
        number_domain="whole", operand_arity=7, step_count=2, grade_band="3-5",
    ),
    params_document={
        "params_version": 1,
        "fields": [
            {
                "type": "integer", "name": f"v{index}", "label": f"Value {index}",
                "description": f"Ordered value {index} of the set",
                "minimum": 1, "maximum": 99,
            }
            for index in range(1, 8)
        ],
    },
    guard_document={
        "guard_version": 1,
        "predicates": [
            {"predicate": "positive", "value": {"node": "field_ref", "field": "v1"}},
            # `ordered` takes at most MAX_PREDICATE_TERMS (6) terms, so the
            # seven-value ordering is expressed as two overlapping runs.
            {"predicate": "ordered", "direction": "non_decreasing", "terms": [
                {"node": "field_ref", "field": f"v{index}"} for index in range(1, 5)
            ]},
            {"predicate": "ordered", "direction": "non_decreasing", "terms": [
                {"node": "field_ref", "field": f"v{index}"} for index in range(4, 8)
            ]},
        ],
    },
    answer_expression={"node": "field_ref", "field": "v4"},
    teaching_plan={
        "plan_version": 3,
        "learning_objective": "Identify the median of an ordered set of seven whole numbers.",
        "primary_visual": {
            "kind": "ordered_values", "ref": "values",
            "values": [{"node": "field_ref", "field": f"v{index}"} for index in range(1, 8)],
        },
        "strategy": "pair_elimination",
        "beats": [
            {"id": "reveal_values", "kind": "reveal", "targets": [{"visual_ref": "values"}],
             "intent": "show all seven ordered values at once so the set reads as one collection"},
            {"id": "pair_from_outside", "kind": "organize", "targets": [{"visual_ref": "values"}],
             "intent": "pair the smallest with the largest and work inward"},
            {"id": "focus_middle", "kind": "focus",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "the one value left unpaired in the middle is the median"},
            {"id": "state_median", "kind": "conclude",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "state the median of the set"},
        ],
        "variation_seed": "demo-median",
    },
    classifier_bullet="Median of an odd-sized ordered set of whole numbers.",
    primary_visual_ref="values",
    expected_beat_ids=["reveal_values", "pair_from_outside", "focus_middle", "state_median"],
    verified_params=_median_values([3, 5, 6, 8, 9, 12, 15]),
    verified_answer=8,
    negative_params=[
        _median_values([0, 5, 6, 8, 9, 12, 15]),   # witnesses `positive`
        _median_values([9, 5, 6, 8, 9, 12, 15]),   # witnesses the first `ordered` run
        _median_values([3, 5, 6, 8, 3, 12, 15]),   # witnesses the second `ordered` run
    ],
    second_params=_median_values([1, 3, 4, 6, 20, 30, 40]),
    second_answer=6,
)

PERIMETER_LESSON = DemoLesson(
    template_name="rectangle_perimeter",
    source_excerpt="A rectangle measures 8 cm by 3 cm. Find its perimeter.",
    fingerprint=Fingerprint(
        fingerprint_version=1, operation_family="measure", representation_family="shape",
        number_domain="whole", operand_arity=2, step_count=2, grade_band="3-5",
    ),
    params_document={
        "params_version": 1,
        "fields": [
            {"type": "integer", "name": "length", "label": "Length (cm)",
             "description": "Rectangle length", "minimum": 1, "maximum": 20},
            {"type": "integer", "name": "width", "label": "Width (cm)",
             "description": "Rectangle width", "minimum": 1, "maximum": 20},
        ],
    },
    guard_document={
        "guard_version": 1,
        "predicates": [
            {"predicate": "positive", "value": {"node": "field_ref", "field": "length"}},
            {"predicate": "positive", "value": {"node": "field_ref", "field": "width"}},
        ],
    },
    # 2 * (length + width)
    answer_expression={
        "node": "multiply",
        "operands": [
            {"node": "literal", "value": 2.0},
            {"node": "add", "operands": [
                {"node": "field_ref", "field": "length"},
                {"node": "field_ref", "field": "width"},
            ]},
        ],
    },
    teaching_plan={
        "plan_version": 3,
        "learning_objective": "Find the perimeter of a rectangle by tracing its boundary.",
        "primary_visual": {
            "kind": "rectangle_measurement", "ref": "rectangle",
            "length": {"node": "field_ref", "field": "length"},
            "width": {"node": "field_ref", "field": "width"},
            "unit": "cm",
        },
        "strategy": "boundary_trace",
        "beats": [
            {"id": "show_rectangle", "kind": "reveal", "targets": [{"visual_ref": "rectangle"}],
             "intent": "show the rectangle whose boundary will be measured"},
            # boundary_trace attaches the perimeter trace to the first
            # organize/derive/focus beat, so the trace happens here. The two
            # callouts label the measured edges through the declared
            # length_edge/width_edge semantic parts, which is what the static
            # and rendered dimension-anchor gates select on.
            {"id": "trace_boundary", "kind": "organize", "targets": [{"visual_ref": "rectangle"}],
             "intent": "trace the whole boundary once and name the two measured edges",
             "custom_actions": [
                 {"kind": "callout", "text": "length", "target": {
                     "visual_ref": "rectangle", "part": "length_edge", "index": 0, "anchor": "bottom",
                 }},
                 {"kind": "callout", "text": "width", "target": {
                     "visual_ref": "rectangle", "part": "width_edge", "index": 0, "anchor": "left",
                 }},
             ]},
            # The mandated derive beat: emphasize the two length edges, then the
            # two width edges, so the boundary visibly maps onto
            # 2 x (length + width). rectangle_measurement emits edges in the
            # order bottom, right, top, left (see rectangle_measurement.py), so
            # the length pair is edge[0] (bottom) + edge[2] (top) and the width
            # pair is edge[3] (left) + edge[1] (right) -- listed pair by pair,
            # not in index order. `emphasize` defaults to the "focus" role.
            {"id": "pair_the_edges", "kind": "derive", "targets": [{"visual_ref": "rectangle"}],
             "intent": "each length and each width edge occurs twice, so the boundary is 2 × (length + width)",
             "custom_actions": [
                 {"kind": "emphasize", "target": {"visual_ref": "rectangle", "part": "edge", "index": 0}},
                 {"kind": "emphasize", "target": {"visual_ref": "rectangle", "part": "edge", "index": 2}},
                 {"kind": "emphasize", "target": {"visual_ref": "rectangle", "part": "edge", "index": 3}},
                 {"kind": "emphasize", "target": {"visual_ref": "rectangle", "part": "edge", "index": 1}},
             ]},
            {"id": "state_perimeter", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}],
             "intent": "state the perimeter as two times the sum of length and width"},
        ],
        "variation_seed": "demo-perimeter",
    },
    classifier_bullet="Rectangle perimeter from whole-number length and width.",
    primary_visual_ref="rectangle",
    expected_beat_ids=["show_rectangle", "trace_boundary", "pair_the_edges", "state_perimeter"],
    verified_params={"length": 8, "width": 3},
    verified_answer=22,
    negative_params=[
        {"length": 0, "width": 3},
        {"length": 8, "width": 0},
    ],
    second_params={"length": 10, "width": 4},
    second_answer=28,
)


def _proposal(lesson: DemoLesson, observation_id: str) -> dict:
    """The bounded tool payload Bedrock is mocked to return for this lesson.

    The single positive fixture is grounded in the seeded observation (it is the
    one artifact a human verifies), and every guard predicate gets a rejecting
    negative fixture so publication's coverage precondition is satisfiable.
    """
    return {
        "params_document": lesson.params_document,
        "guard_document": lesson.guard_document,
        "answer_expression": lesson.answer_expression,
        "teaching_plan_document": lesson.teaching_plan,
        "classifier_bullet": lesson.classifier_bullet,
        "fixtures": [
            {"kind": "positive", "expected_outcome": "accept", "generation_method": "proposed",
             "observation_id": observation_id, "params": lesson.verified_params},
            *(
                {"kind": "negative", "expected_outcome": "reject",
                 "generation_method": "proposed", "observation_id": None, "params": params}
                for params in lesson.negative_params
            ),
        ],
    }


# ------------------------------------------------- manifest -> contract report


_EMPHASIS_ROLES = frozenset({"focus", "conclusion"})


def _emphasis_state_order(state_events) -> list[str]:
    """Observed role trajectory of every target the lesson ever emphasizes.

    A demo beat singles out exactly one collection item and the evaluated
    answer. Restricting the trajectory to targets that eventually reach an
    emphasis role keeps every state those targets actually passed through (so a
    value styled in the wrong order still shows up) while dropping the bulk
    background roles applied to the items the lesson never singles out.
    """
    emphasized = {
        event["target"] for event in state_events if event["role"] in _EMPHASIS_ROLES
    }
    return [
        f"{event['target']}:{event['role']}"
        # A stable sort keeps same-instant events in the order they were observed.
        for event in sorted(state_events, key=lambda event: event["seconds"])
        if event["target"] in emphasized
    ]


# A sampled frame's `seconds` is the beat's scheduled end, but a state event's
# `seconds` is the probe's own accumulated elapsed time, which lands a fraction
# of a nanosecond above that end (the compiler rounds timeline entries to nine
# decimal places). This tolerance absorbs that drift while staying orders of
# magnitude below the 0.15s minimum action length, so an event on a beat
# boundary is still credited to the beat that produced it.
_BEAT_BOUNDARY_TOLERANCE_SECONDS = 1e-6


def _emphasis_targets_by_beat(frames, state_events) -> dict[str, set[str]]:
    """Targets the renderer was observed to actually emphasize, per teaching beat.

    Beat windows come from the probe's own sampled frames -- one per beat, each
    stamped with that beat's id and the second it ended -- so no timing is
    hardcoded here. Every sampled beat gets an entry, including an empty one, so
    an assertion about a beat that stopped emphasizing anything fails on the
    comparison instead of on a missing key.
    """
    ordered = sorted(frames, key=lambda frame: frame["seconds"])
    by_beat: dict[str, set[str]] = {frame["beat_id"]: set() for frame in ordered}
    for event in state_events:
        if event["role"] != "focus":
            continue
        beat_id = next(
            (
                frame["beat_id"] for frame in ordered
                if event["seconds"] <= frame["seconds"] + _BEAT_BOUNDARY_TOLERANCE_SECONDS
            ),
            None,
        )
        if beat_id is not None:
            by_beat[beat_id].add(event["target"])
    return by_beat


def build_demo_quality_report(manifest: dict) -> dict:
    """Project probe-manifest evidence onto the fields the demo contracts read.

    The one and only place the manifest -> contract-field mapping lives. Every
    value is renderer-observed probe evidence: nothing here re-derives an
    expectation from the scene program, and the single computed number
    (``alignment_error``) uses production's own distance function.
    """
    width, height = manifest["frame_size"]
    return {
        "total_duration_seconds": manifest["total_duration_seconds"],
        "conclusion_hold_seconds": manifest["conclusion_hold_seconds"],
        "simple_reveal_mode": manifest["simple_reveal_mode"],
        "anchor_tolerance": ANCHOR_TOLERANCE,
        "state_order": _emphasis_state_order(manifest["state_events"]),
        "emphasis_targets_by_beat": _emphasis_targets_by_beat(
            manifest["frames"], manifest["state_events"]
        ),
        "relations": {
            ref: {
                **relation,
                "alignment_error": _normalized_distance(
                    relation["target"], relation["tip"], width, height
                ),
            }
            for ref, relation in manifest["relations"].items()
        },
        "traced_paths": list(manifest["path_events"]),
        "dimension_anchor_checks": {
            ref: outcome["passed"]
            for ref, outcome in manifest["dimension_anchor_checks"].items()
        },
        "derivation_visible": manifest["derivation_visible"],
    }


# ------------------------------------------------------------- runbook driver


@dataclass(frozen=True)
class DemoRenderResult:
    """Everything one demo lesson's runbook produced, for later assertion."""

    lesson: DemoLesson
    draft_id: str
    scene_program: SceneProgramDocument
    published_program: SceneProgramDocument
    stored_quality_report: dict
    validation_report: dict
    manifest: dict
    quality_report: dict
    preview_artifact_hash: str
    reprobed_artifact_hash: str
    preview_bytes: bytes
    mp4_path: Path
    dimension_relation_refs: frozenset[str]
    resolved: dict
    runbook: dict


def _unsupported_shape_classification() -> ClassificationResult:
    return ClassificationResult(
        grade_level=4, ambiguous=False, problem_kind="solvable",
        options=[TemplateOption(template=TemplateName.TEXT_CARD, rationale="no structural match")],
    )


def _dimension_relation_refs(program: SceneProgramDocument) -> frozenset[str]:
    """Refs of the callout relations the real compiler emitted as dimension labels.

    Derived from the compiled program using production's own
    ``DIMENSION_TARGET_PARTS``, never from a hand-copied ref: the beat expander
    names callout relations ``callout_{beat}_{action}``, so a literal list here
    would silently rot.
    """
    return frozenset(
        relation.ref for relation in program.relations
        if relation.target.part in DIMENSION_TARGET_PARTS
    )


def _run_demo_lesson(client: TestClient, lesson: DemoLesson, tmp_path: Path) -> DemoRenderResult:
    """Perform the runbook for one lesson, recording each step's real evidence."""
    candidate_id = f"{lesson.template_name}-slide-1"
    with patch("app.meta.fingerprint.call_with_tool") as tag_call:
        tag_call.return_value = ("fingerprint", lesson.fingerprint.model_dump())
        record_unsupported_shape(
            candidate_id=candidate_id,
            source_excerpt=lesson.source_excerpt,
            classification=_unsupported_shape_classification(),
            picked_template=TemplateName.TEXT_CARD,
            scene_status="pending_review",
        )
    with meta_session() as session:
        observation_id = (
            session.query(models.FallbackObservation)
            .filter_by(candidate_id=candidate_id)
            .one()
            .id
        )

    with patch("app.meta.draft_generation.call_with_tool") as draft_call:
        draft_call.return_value = ("propose_template_draft", _proposal(lesson, observation_id))
        draft = run_generation_job(owner="worker-1")
    assert draft is not None, "the demo lesson must generate a persistable draft"

    draft_id = draft.id
    runbook = {"draft_status": draft.status}
    runbook["pending_ids"] = [row["id"] for row in client.get("/meta/drafts").json()]
    detail = client.get(f"/meta/drafts/{draft_id}").json()
    runbook["detail"] = detail
    preview = client.get(detail["preview_url"])
    runbook["preview_status"] = preview.status_code

    runbook["positive_fixtures"] = [
        fixture for fixture in detail["fixtures"] if fixture["kind"] == "positive"
    ]
    save = client.post(
        f"/meta/drafts/{draft_id}/fixtures/{runbook['positive_fixtures'][0]['id']}",
        json={
            "params": lesson.verified_params,
            "expected_result": {"answer": lesson.verified_answer},
        },
    )
    runbook["fixture_save_status"] = save.status_code
    runbook["fixture_save"] = save.json()
    runbook["detail_after_verify"] = client.get(f"/meta/drafts/{draft_id}").json()

    approval = client.post(
        f"/meta/drafts/{draft_id}/approve",
        json={"template_name": lesson.template_name, "math_semantics_confirmed": True},
    )
    runbook["approval_status"] = approval.status_code
    runbook["approval"] = approval.json()
    # The runbook must not read a decided draft's detail: it 404s once the draft
    # leaves pending_review, and the review list only ever shows pending drafts.
    runbook["detail_status_after_approval"] = client.get(f"/meta/drafts/{draft_id}").status_code
    runbook["pending_ids_after_approval"] = [
        row["id"] for row in client.get("/meta/drafts").json()
    ]

    with meta_session() as session:
        row = session.get(models.TemplateDraft, draft_id)
        scene_program = SceneProgramDocument.model_validate_json(row.scene_program_json)
        stored_quality_report = json.loads(row.quality_report_json)
        validation_report = json.loads(row.validation_report_json)
        preview_artifact_hash = row.preview_artifact_hash

        entry = load_enabled_snapshot(session).entry(lesson.template_name)
        assert entry is not None, "approval must publish an enabled template version"
        ref = resolve_dynamic_ref(session, lesson.template_name, entry.version_id)
    scene_cls, params_cls = get_dynamic_template(ref)
    published_program = scene_cls.scene_program

    # Re-probe the *published* program at the reviewed values: this is the
    # renderer-observed evidence the acceptance contracts assert against, and
    # its artifact hash is comparable with the preview the reviewer approved.
    reprobed_hash, manifest = render_preview_and_probe(
        published_program,
        lesson.known_fields,
        lesson.verified_params,
        get_settings().meta_artifact_root,
    )

    resolved = {
        "verified": resolve_dynamic_scene(published_program, lesson.verified_params),
        "second": resolve_dynamic_scene(published_program, lesson.second_params),
    }
    mp4_path = tmp_path / f"{lesson.template_name}-slide-2.mp4"
    render_scene_to_mp4(ref, params_cls.model_validate(lesson.second_params), mp4_path)

    return DemoRenderResult(
        lesson=lesson,
        draft_id=draft_id,
        scene_program=scene_program,
        published_program=published_program,
        stored_quality_report=stored_quality_report,
        validation_report=validation_report,
        manifest=manifest,
        quality_report=build_demo_quality_report(manifest),
        preview_artifact_hash=preview_artifact_hash,
        reprobed_artifact_hash=reprobed_hash,
        preview_bytes=preview.content,
        mp4_path=mp4_path,
        dimension_relation_refs=_dimension_relation_refs(scene_program),
        resolved=resolved,
        runbook=runbook,
    )


@pytest.fixture
def rendered_median(client, tmp_path):
    return _run_demo_lesson(client, MEDIAN_LESSON, tmp_path)


@pytest.fixture
def rendered_perimeter(client, tmp_path):
    return _run_demo_lesson(client, PERIMETER_LESSON, tmp_path)


# --------------------------------------------------------- runbook assertions


def _answer_text(resolved) -> str:
    return resolved.visual("evaluated_answer").measured.payload["text"]


def _geometry_signature(resolved, visual_ref: str):
    """Every resolved semantic-part bound of a visual, for a re-resolution check."""
    return tuple(sorted(
        (part, index, value.bounds.left, value.bounds.right,
         value.bounds.bottom, value.bounds.top)
        for (part, index), value in resolved.visual(visual_ref).measured.parts.items()
    ))


def _evaluate_answer(lesson: DemoLesson, values: dict) -> Fraction:
    node = _EXPRESSION.validate_python(lesson.answer_expression)
    return compile_expression(node, lesson.known_fields).evaluate(values)


@pytest.mark.parametrize("lesson_fixture", ["rendered_median", "rendered_perimeter"])
def test_demo_runbook_generates_reviews_publishes_and_reuses(lesson_fixture, request):
    result = request.getfixturevalue(lesson_fixture)
    lesson, runbook = result.lesson, result.runbook
    detail = runbook["detail"]

    # 1-3. The worker generated a candidate and validated it privately. A draft
    # that fails any gate never reaches pending_review, so the presenter never
    # walks a failed-validation draft.
    assert runbook["draft_status"] == models.DRAFT_PENDING_REVIEW
    assert runbook["pending_ids"] == [result.draft_id]

    # 4. Review: teaching beats, a bounded duration, and passing evidence.
    beats = detail["teaching_plan"]["beats"]
    assert [beat["id"] for beat in beats] == lesson.expected_beat_ids
    assert 3 <= len(beats) <= 5
    assert beats[-1]["kind"] == "conclude"
    assert detail["teaching_plan"]["strategy"] == lesson.teaching_plan["strategy"]
    assert 6 <= detail["total_duration_seconds"] <= 12
    assert detail["timeline"]
    assert detail["validation_report"]["passed"] is True
    assert detail["quality_report"]["passed"] is True
    assert [check for check in detail["quality_report"]["checks"] if not check["passed"]] == []
    # Reviewer-visible payloads never carry internal retry or stack-trace detail.
    assert "traceback" not in json.dumps(detail).lower()

    # The evidence the reviewer reads is the evidence stored on the draft, and
    # both reports certify the artifact that is about to be approved -- a report
    # whose artifact_hash does not match the draft is stale and blocks approval.
    assert result.stored_quality_report == detail["quality_report"]
    assert result.validation_report == detail["validation_report"]
    assert result.stored_quality_report["artifact_hash"] == detail["artifact_hash"]
    assert result.validation_report["artifact_hash"] == detail["artifact_hash"]

    # The preview is a real, stored, non-blank PNG.
    assert runbook["preview_status"] == 200
    assert result.preview_bytes.startswith(b"\x89PNG")

    # Only the grounded positive fixture is offered for verification.
    assert len(runbook["positive_fixtures"]) == 1
    assert runbook["positive_fixtures"][0]["source_excerpt"] == lesson.source_excerpt

    # 4b. The reviewer confirms the known answer. Confirming it for unchanged
    # params must not invalidate the evidence that makes the draft approvable.
    assert runbook["fixture_save_status"] == 200
    assert runbook["fixture_save"]["expected_result"] == {"answer": str(lesson.verified_answer)}
    assert runbook["fixture_save"]["structural_check_passed"] is True
    assert runbook["detail_after_verify"]["validation_report"]["passed"] is True
    assert runbook["detail_after_verify"]["quality_report"]["passed"] is True
    assert runbook["detail_after_verify"]["preview_url"]

    # 5. Approve and publish; the decided draft leaves the reviewer's world.
    assert runbook["approval_status"] == 200, runbook["approval"]
    assert runbook["approval"]["status"] == "enabled"
    assert runbook["approval"]["template_name"] == lesson.template_name
    assert runbook["detail_status_after_approval"] == 404
    assert runbook["pending_ids_after_approval"] == []

    # 6. The runtime carries the stored scene program verbatim -- it is not
    # recompiled at load time -- and re-resolving and re-rendering that
    # published program reproduces the approved preview byte for byte.
    assert result.published_program == result.scene_program
    assert result.published_program.total_duration_seconds == detail["total_duration_seconds"]
    assert result.reprobed_artifact_hash == result.preview_artifact_hash

    # 7. Reuse on slide 2: layout, anchors and the evaluated answer all
    # re-resolve for the new parameter set.
    assert _answer_text(result.resolved["verified"]) == str(lesson.verified_answer)
    assert _answer_text(result.resolved["second"]) == str(lesson.second_answer)
    assert _geometry_signature(result.resolved["verified"], lesson.primary_visual_ref) != (
        _geometry_signature(result.resolved["second"], lesson.primary_visual_ref)
    )
    assert result.mp4_path.exists() and result.mp4_path.stat().st_size > 0


def test_demo_answers_are_correct_for_both_slides_of_both_lessons():
    # Semantic guard, independent of rendering: each published template's answer
    # expression resolves to the answers the runbook tells the presenter to expect.
    for lesson in (MEDIAN_LESSON, PERIMETER_LESSON):
        assert _evaluate_answer(lesson, lesson.verified_params) == Fraction(lesson.verified_answer)
        assert _evaluate_answer(lesson, lesson.second_params) == Fraction(lesson.second_answer)
