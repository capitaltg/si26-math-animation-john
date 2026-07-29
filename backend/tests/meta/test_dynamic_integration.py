"""End-to-end acceptance fixture for an approved dynamic template (Task 11).

Drives a real request through the entire dynamic-template stack --
classify_candidate -> resolve_dynamic_ref -> get_template -> extract_params ->
assemble_scene -> render_scene_to_mp4/thumbnail -- mocking only the two true
external boundaries: Bedrock (`call_with_tool`, at both its classification.py
and extraction.py call sites) and the render subprocess (`subprocess.run`).

No shared tests/meta/conftest.py exists yet (see test_dynamic_templates.py's
own comment on this), and this task's Code Organization instructions say to
create only this one file, so the engine/session fixtures below duplicate the
same local pattern used across tests/meta/ (test_approval.py,
test_validation_pipeline.py, test_drafts.py, test_dynamic_templates.py, ...)
rather than promoting anything to a new conftest.py.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.meta import db
from app.meta.dynamic_templates import resolve_dynamic_ref
from app.models.candidate import Candidate
from app.pipeline.classification import classify_candidate
from app.pipeline.process_scene import assemble_scene
from app.templates.registry import get_template
from tests.meta.test_dynamic_templates import _seed_draft_and_version


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


def test_approved_dynamic_template_flows_end_to_end(session, tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "meta_dynamic_classifier_enabled", True)
    _draft, version = _seed_draft_and_version(session, template_name="my_dynamic_template")

    with patch("app.pipeline.classification.call_with_tool") as mock_call:
        mock_call.return_value = (
            "classify_problem",
            {
                "options": [
                    {"template": "my_dynamic_template", "rationale": "matches the shape"},
                ],
                "grade_level": 3,
                "ambiguous": False,
            },
        )
        classification = classify_candidate("A is 3 and B is 4.", session=session)

    dynamic_option = next(o for o in classification.options if o.template == "my_dynamic_template")
    assert dynamic_option.version_id == version.id

    template_ref = resolve_dynamic_ref(session, dynamic_option.template, dynamic_option.version_id)

    # Confirm the seeded params document's real field names ("a"/"b", per
    # _seed_draft_and_version) before trusting the extraction mock below --
    # get_template(template_ref) returns the exact dynamically-compiled
    # params_cls this candidate will be validated against.
    _, params_cls = get_template(template_ref)
    assert set(params_cls.model_fields) >= {"a", "b"}

    candidate = Candidate(
        candidate_id="c1",
        source_excerpt="A is 3 and B is 4.",
        slide_index=0,
        one_line_summary="Detected: 3 and 4",
    )

    with patch("app.pipeline.extraction.call_with_tool") as mock_extract, patch(
        "app.render.full_render.subprocess.run"
    ) as mock_run:
        mock_extract.return_value = ("report_params", {"a": 3, "b": 4})
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        scene = assemble_scene(candidate, tmp_path, template=template_ref, grade=3)

    assert scene.status == "pending_review"
    assert scene.template == template_ref
    assert scene.params == {"a": 3, "b": 4}
    assert scene.thumbnail_path is not None
    mock_extract.assert_called_once()
    mock_run.assert_called_once()
