"""Executable acceptance contracts for the two demo lessons.

These are the plan's last gate: each assertion reads renderer-observed probe
evidence for the *published* median and perimeter templates (see
``tests/meta/test_demo_end_to_end.py`` for the runbook that produces it) and
compares it against what the lesson must teach. Expected values are derived from
the real compiler and the real probe manifest, never copied out of a passing
run, so a regression in compilation, layout, resolution, styling or rendering
fails a named assertion here.

Two tiers of assertion live below, and the difference matters when reading a
failure:

*Load-bearing* -- the only checks here that no shipped gate already enforces, so
these are the contract's real teeth: ``simple_reveal_mode``, ``state_order``,
the callout's ``target_anchor``, ``traced_paths``, the non-empty dimension-refs
guard, and the derive beat's observed edge emphasis.

*Deliberately redundant* -- assertions restating a gate that already ran before
the fixture returned, so they can never be the failing line: a violation raises
inside the fixture (rendered gates run in ``render_preview_and_probe``) or keeps
the draft from ever being persisted (static gates run pre-persist). They are
kept verbatim as the plan wrote them, for plan fidelity and as documentation of
the contract; each one names the gate that actually enforces it.
"""

from tests.meta.test_demo_end_to_end import (  # noqa: F401  (imported as pytest fixtures)
    client,
    rendered_median,
    rendered_perimeter,
)


def test_rendered_median_meets_v3_contract(rendered_median):
    report = rendered_median.quality_report

    # Redundant: static `check_duration` already bounds this at 6/12 pre-persist.
    assert 6 <= report["total_duration_seconds"] <= 12
    # Load-bearing: the collection reveals as one group rather than trickling in
    # item by item.
    assert report["simple_reveal_mode"] == "together"

    # Load-bearing: every emphasized target's observed styling trajectory. The
    # median item is neutral before it is focused, and the evaluated answer only
    # reaches its conclusion styling at the end.
    assert report["state_order"] == [
        "values.item[3]:neutral",
        "values.item[3]:focus",
        "evaluated_answer:conclusion",
    ]

    # Load-bearing: the callout is anchored to the median item itself, not to the
    # collection as a whole.
    median_callout = report["relations"]["median_callout"]
    assert median_callout["target_anchor"] == "values.item[3].bottom"
    # Redundant: rendered `check_relation_alignment` already compares this exact
    # distance against this exact tolerance, and raises inside the fixture.
    assert median_callout["alignment_error"] <= report["anchor_tolerance"]

    # Redundant: static `check_conclusion_hold` already enforces the 1.5s floor.
    assert report["conclusion_hold_seconds"] >= 1.5


def test_rendered_perimeter_meets_v3_contract(rendered_perimeter):
    report = rendered_perimeter.quality_report
    lesson = rendered_perimeter.lesson

    # Redundant: static `check_duration` already bounds this at 6/12 pre-persist.
    assert 6 <= report["total_duration_seconds"] <= 12

    # Load-bearing: the boundary is actually traced, so the perimeter is shown as
    # a process rather than asserted.
    assert "rectangle.perimeter" in report["traced_paths"]

    # Load-bearing: the lesson's measurements are actually on screen. This used
    # to assert dimension CALLOUTS were rendered and anchored; a callout's text
    # is a plain string frozen at generation time, so it could not survive the
    # template being reused on another problem. `rectangle_measurement` now
    # measures and draws the dimensions from the length/width expressions, so the
    # evidence is the rendered label text -- read off the mobjects, and matching
    # this fixture's own field values rather than a hardcoded pair.
    assert report["declared_dimension_labels"] == [lesson.primary_visual_ref]
    assert report["dimension_labels"][lesson.primary_visual_ref] == {
        "length_label": f"{lesson.verified_params['length']} cm",
        "width_label": f"{lesson.verified_params['width']} cm",
    }

    # Load-bearing, and the only guard on the mandated derive beat: within that
    # beat the renderer really emphasized all four edges -- the length pair
    # (bottom, top) and the width pair (left, right) -- which is what maps the
    # boundary onto 2 x (length + width). No shipped gate checks this, and
    # `derivation_visible` below cannot catch it: the worker derives that flag as
    # `bool(path_events) or any(focus)`, so the traced perimeter asserted above
    # already forces it True regardless of what the derive beat does.
    derive_beat_id = lesson.derive_beat_id
    assert derive_beat_id, "the perimeter lesson must teach the pairing in a derive beat"
    assert report["emphasis_targets_by_beat"][derive_beat_id] == {
        f"{lesson.primary_visual_ref}.edge[{index}]" for index in range(4)
    }

    # Redundant: implied by the traced path asserted above (see the comment on
    # the derive-beat assertion for why).
    assert report["derivation_visible"] is True

    # Redundant: static `check_conclusion_hold` already enforces the 1.5s floor.
    assert report["conclusion_hold_seconds"] >= 1.5
