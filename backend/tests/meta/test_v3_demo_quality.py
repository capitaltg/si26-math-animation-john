"""Executable acceptance contracts for the two demo lessons.

These are the plan's last gate: each assertion reads renderer-observed probe
evidence for the *published* median and perimeter templates (see
``tests/meta/test_demo_end_to_end.py`` for the runbook that produces it) and
compares it against what the lesson must teach. Expected values are derived from
the real compiler and the real probe manifest, never copied out of a passing
run, so a regression in compilation, layout, resolution, styling or rendering
fails a named assertion here.
"""

from tests.meta.test_demo_end_to_end import (  # noqa: F401  (imported as pytest fixtures)
    client,
    rendered_median,
    rendered_perimeter,
)


def test_rendered_median_meets_v3_contract(rendered_median):
    report = rendered_median.quality_report

    # Standard animation duration, and the collection reveals as one group
    # rather than trickling in item by item.
    assert 6 <= report["total_duration_seconds"] <= 12
    assert report["simple_reveal_mode"] == "together"

    # Every emphasized target's observed styling trajectory: the median item is
    # neutral before it is focused, and the evaluated answer only reaches its
    # conclusion styling at the end.
    assert report["state_order"] == [
        "values.item[3]:neutral",
        "values.item[3]:focus",
        "evaluated_answer:conclusion",
    ]

    # The item-specific callout is anchored to the median item itself, and the
    # rendered arrow tip really lands on that anchor.
    median_callout = report["relations"]["median_callout"]
    assert median_callout["target_anchor"] == "values.item[3].bottom"
    assert median_callout["alignment_error"] <= report["anchor_tolerance"]

    assert report["conclusion_hold_seconds"] >= 1.5


def test_rendered_perimeter_meets_v3_contract(rendered_perimeter):
    report = rendered_perimeter.quality_report

    assert 6 <= report["total_duration_seconds"] <= 12

    # The boundary is actually traced, so the perimeter is shown as a process.
    assert "rectangle.perimeter" in report["traced_paths"]

    # Both dimension labels stay attached to the edges they measure. The refs
    # come from the compiled program (the compiler names callout relations
    # positionally), and the non-empty guard means a dimension filter that stops
    # matching real programs fails here instead of comparing {} == {}.
    dimension_refs = rendered_perimeter.dimension_relation_refs
    assert dimension_refs, "the perimeter plan's edge callouts must compile to dimension relations"
    assert report["dimension_anchor_checks"] == {ref: True for ref in dimension_refs}

    # The derivation is visible on screen, not merely implied by the answer.
    assert report["derivation_visible"] is True

    assert report["conclusion_hold_seconds"] >= 1.5
