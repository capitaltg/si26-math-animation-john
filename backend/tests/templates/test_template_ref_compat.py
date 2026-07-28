from unittest.mock import patch

import pytest

from app.models.scene import TemplateName
from app.templates.registry import get_chained_template, get_template, resolve_static_ref, static_ref

ALL_STATIC_TEMPLATES = [
    TemplateName.NUMBER_LINE,
    TemplateName.ARRAY_GRID,
    TemplateName.TEXT_CARD,
    TemplateName.FRACTION_BAR,
    TemplateName.BALANCE_SCALE,
    TemplateName.FRACTION_OF_WHOLE,
]

CHAINABLE_STATIC_TEMPLATES = [
    TemplateName.NUMBER_LINE,
    TemplateName.ARRAY_GRID,
    TemplateName.FRACTION_BAR,
    TemplateName.BALANCE_SCALE,
    TemplateName.FRACTION_OF_WHOLE,
]


@pytest.mark.parametrize("name", ALL_STATIC_TEMPLATES)
def test_every_static_template_resolves_to_a_stable_ref(name):
    ref = static_ref(name)
    assert ref.name == name
    assert ref.version_id == "1"
    assert ref.artifact_hash.startswith("sha256:")
    assert ref == static_ref(name)


@pytest.mark.parametrize("name", ALL_STATIC_TEMPLATES)
def test_every_static_template_ref_resolves_through_get_template(name):
    ref = static_ref(name)
    scene_cls, params_cls = get_template(ref)
    assert scene_cls.__name__.lower().startswith(name.value.replace("_", ""))
    assert params_cls is not None


@pytest.mark.parametrize("name", CHAINABLE_STATIC_TEMPLATES)
def test_every_chainable_static_template_ref_resolves_through_get_chained_template(name):
    ref = static_ref(name)
    scene_cls, params_cls = get_chained_template(ref)
    assert scene_cls is not None
    assert params_cls is not None


def test_two_different_static_templates_never_collide_on_hash():
    hashes = {name: static_ref(name).artifact_hash for name in ALL_STATIC_TEMPLATES}
    assert len(set(hashes.values())) == len(hashes)


@patch("app.pipeline.classification.call_with_tool")
def test_classify_pick_and_build_scene_round_trips_the_same_ref(mock_call, tmp_path):
    from app.pipeline.classification import classify_candidate
    from app.pipeline.process_scene import assemble_scene
    from app.models.candidate import Candidate

    mock_call.return_value = (
        "classify_problem",
        {
            "options": [{"template": "number_line", "rationale": "one jump"}],
            "grade_level": 1,
            "ambiguous": False,
        },
    )
    classification = classify_candidate("6 + 3 = ?")
    picked = next(o for o in classification.options if o.template == TemplateName.NUMBER_LINE)
    resolved = resolve_static_ref(picked.template, picked.version_id)
    assert resolved.version_id == picked.version_id

    candidate = Candidate(
        candidate_id="c1", source_excerpt="6 + 3 = ?", slide_index=0,
        one_line_summary="Detected: 6 + 3",
    )
    with patch("app.pipeline.process_scene.extract_params") as mock_extract, \
         patch("app.pipeline.process_scene.render_scene_thumbnail"):
        from app.templates.number_line.params import NumberLineParams

        mock_extract.return_value = NumberLineParams(
            start=6, steps=[{"operation": "add", "amount": 3}]
        )
        scene = assemble_scene(candidate, tmp_path, template=resolved, grade=1)

    assert scene.template == resolved
