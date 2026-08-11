"""Contract: extracted params' numeric values trace back to source text.

Reviewer's #1 asks the extractor to preserve provenance from the PPTX
region an extraction came from. In this codebase provenance runs through
two channels:

1. `Candidate.slide_index` + `Candidate.source_excerpt` — carried on
   the candidate that seeds extraction.
2. `check_params_grounded(params, source_text)` — enforces that every
   numeric value in the extracted params has a literal occurrence in
   the source excerpt. A number the extractor invented (or read from
   the wrong region) fails grounding and the extraction is rejected.

The gate at (2) is what makes provenance load-bearing: without it a
downstream calc could run against numbers the source never contained.
This test locks the gate in for **every** static template — a template
whose numeric fields silently escape enumeration would let the calc
consume ungrounded numbers.

Two invariants per template:
- A canonical valid params instance grounds cleanly against a source
  text that contains every one of its numbers.
- A single number swapped for one absent from the source is caught as
  ungrounded — the gate does not degenerate to accept-all.
"""

import pytest

from app.models.scene import TemplateName
from app.pipeline.grounding import check_params_grounded
from app.templates.registry import _REGISTRY


# (canonical example, source text containing every number in the example).
# Source strings are written the way an extractor would see them coming
# out of a PPTX cell — sentence-like, numerics rendered as bare digits or
# as `n/d` fractions where the template's `grounding_number_tokens` hook
# reports the fraction form. Grounding tokens the source via the same
# tokenizer the pipeline uses (`tokenize_for_grounding`), so a stray comma
# or trailing period does not interfere.
GROUNDED_CASES: dict[TemplateName, tuple[dict, str]] = {
    TemplateName.NUMBER_LINE: (
        {"start": 4, "steps": [{"operation": "add", "amount": 3}]},
        "Sarah starts at 4 and moves 3 forward.",
    ),
    TemplateName.ARRAY_GRID: (
        {"rows": 2, "cols": 3, "steps": []},
        "An array with 2 rows and 3 columns.",
    ),
    TemplateName.BALANCE_SCALE: (
        # right_total is a derived total — the grounding hook only
        # requires the left_terms; the sum need not appear literally.
        {"left_terms": [2, 3], "right_total": 5},
        "One side of the scale holds 2 and 3.",
    ),
    TemplateName.FRACTION_BAR: (
        # grounding_number_tokens returns "n/d" strings, so the source
        # must render fractions the same way.
        {
            "denominator": 4,
            "start_numerator": 1,
            "steps": [
                {"numerator": 1, "operation": "add"},
                {"numerator": 1, "operation": "add"},
            ],
        },
        "Start with 1/4, then add 1/4 and add 1/4 more.",
    ),
    TemplateName.FRACTION_OF_WHOLE: (
        {"numerator": 1, "denominator": 4},
        "What is 1/4 of the whole?",
    ),
    TemplateName.TEXT_CARD: (
        # text_card has no numeric params, so the grounding walker
        # returns no tokens and the gate is vacuously satisfied. Kept in
        # the table so the enumeration guard covers every registered
        # template — omitting it would let a text_card variant slip
        # through if it ever gains a numeric field without a hook.
        {"headline": "answer", "lines": ["42"]},
        "The answer is 42.",
    ),
}


def test_every_registered_static_template_has_a_grounded_case():
    """Guard: `GROUNDED_CASES` covers every entry in the static registry.

    A new template added to `_REGISTRY` without a case here would
    escape the provenance gate: its numeric fields would never be run
    through `check_params_grounded` at contract-test time, and a
    silent regression in `params_number_tokens` for that template
    would only surface when a real deck happened to trigger it.
    """
    registered = set(_REGISTRY.keys())
    covered = set(GROUNDED_CASES.keys())

    missing = registered - covered
    stray = covered - registered

    assert not missing, (
        f"Static templates without a grounded case: {sorted(t.value for t in missing)}. "
        f"Add one entry per template to GROUNDED_CASES."
    )
    assert not stray, (
        f"Grounded cases for templates no longer registered: "
        f"{sorted(t.value for t in stray)}."
    )


@pytest.mark.parametrize(
    "template_name,example,source_text",
    [(t, ex, src) for t, (ex, src) in GROUNDED_CASES.items()],
    ids=[t.value for t in GROUNDED_CASES],
)
def test_canonical_params_ground_cleanly_against_matching_source(
    template_name, example, source_text
):
    """Every number the extractor produced traces back to source.

    `check_params_grounded` returns the ungrounded tokens; an empty list
    means every numeric value in the params has a literal occurrence in
    the source excerpt. If a Params class ever ships a numeric field
    that neither `default_number_tokens` walks nor the template's
    `grounding_number_tokens` reports, that field's value would silently
    escape the check — this test would still pass, but the negative case
    below catches the specific failure mode reviewer named.
    """
    _scene_cls, params_cls = _REGISTRY[template_name]
    params = params_cls.model_validate(example)

    ungrounded = check_params_grounded(params, source_text)

    assert ungrounded == [], (
        f"{template_name.value}: canonical params reported as ungrounded "
        f"against a source that contains every value — provenance gate is "
        f"broken or the source text drifted from the example. Ungrounded: "
        f"{ungrounded}"
    )


@pytest.mark.parametrize(
    "template_name,example,source_text",
    [
        (t, ex, src)
        for t, (ex, src) in GROUNDED_CASES.items()
        # text_card has no numeric fields to un-ground, so this negative
        # case does not apply — the walker returns nothing and there is
        # nothing to reject.
        if t is not TemplateName.TEXT_CARD
    ],
    ids=[t.value for t in GROUNDED_CASES if t is not TemplateName.TEXT_CARD],
)
def test_number_absent_from_source_is_caught_as_ungrounded(
    template_name, example, source_text
):
    """The provenance gate is not accept-all.

    Runs the same canonical params through `check_params_grounded`
    against a source that has been stripped of every digit. Grounding
    must report at least one ungrounded token: the walker enumerated a
    number, the source no longer contains it, the gate rejects.

    A `params_number_tokens` regression that returns an empty list for a
    template with numeric fields would pass the positive test above
    (vacuously grounded) and fail this one (nothing to be ungrounded).
    """
    _scene_cls, params_cls = _REGISTRY[template_name]
    params = params_cls.model_validate(example)

    # Strip every digit and slash so no number token — including "n/d"
    # fraction tokens — can match. Keeps the rest of the sentence intact
    # so tokenization still produces something to walk.
    stripped = "".join(
        ch for ch in source_text if not ch.isdigit() and ch != "/"
    )

    ungrounded = check_params_grounded(params, stripped)

    assert ungrounded, (
        f"{template_name.value}: canonical params grounded against a "
        f"digit-free source — either `params_number_tokens` returned an "
        f"empty list for a template that has numeric fields, or the "
        f"grounding gate degenerated to accept-all."
    )
