"""Every field that drives a part count must say so in the tool schema.

`draft_generation.propose_template_draft` sends `DraftProposal.model_json_schema()`
to Bedrock, so a field's `description` is documentation the model actually reads.
`BarVisual.maximum` had none, and the model read it as an axis maximum: it
proposed 10000 for a 2750-metre answer, which `_measure_bar` would have built as
10000 rectangles.
"""

from app.meta.draft_generation import DraftProposal
from app.meta.v3.visual_registry import MAX_PART_CARDINALITY, MAX_TAPE_BOXES

#: Model class name -> (fields whose value decides how many parts get drawn, that
#: kind's own cap). Per-kind because a tape's cap (`MAX_TAPE_BOXES`, 8) is not
#: `MAX_PART_CARDINALITY` (128) -- the two kinds bound different things.
COUNT_DRIVEN_FIELDS = {
    "BarVisual": (("maximum",), MAX_PART_CARDINALITY),
    "GridVisual": (("rows", "columns"), MAX_PART_CARDINALITY),
    "ObjectSetVisual": (("count",), MAX_PART_CARDINALITY),
    "PartitionVisual": (("parts",), MAX_PART_CARDINALITY),
    "UnitTapeVisual": (("value",), MAX_TAPE_BOXES),
}


def _description(definitions, model_name, field_name) -> str:
    return definitions[model_name]["properties"][field_name].get("description", "")


def test_every_count_driven_field_states_its_cap_and_an_alternative():
    definitions = DraftProposal.model_json_schema()["$defs"]

    for model_name, (field_names, cap) in COUNT_DRIVEN_FIELDS.items():
        for field_name in field_names:
            description = _description(definitions, model_name, field_name)
            assert str(cap) in description, f"{model_name}.{field_name} omits the cap"
            assert "number_line" in description, f"{model_name}.{field_name} omits the alternative"


def test_the_number_line_scale_is_not_described_as_a_count():
    """`number_line.maximum` and `bar.maximum` share a name and mean opposites."""
    definitions = DraftProposal.model_json_schema()["$defs"]

    description = _description(definitions, "NumberLineVisual", "maximum")
    assert "scale" in description
    assert str(MAX_PART_CARDINALITY) not in description
