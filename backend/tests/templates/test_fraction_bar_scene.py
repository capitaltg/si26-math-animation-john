from app.models.scene import TemplateName
from app.render.full_render import render_scene_to_mp4
from app.templates.fraction_bar.params import FractionBarParams, FractionStep


def test_fraction_bar_renders_to_mp4(tmp_path):
    params = FractionBarParams(
        denominator=4,
        start_numerator=1,
        steps=[
            FractionStep(operation="add", numerator=2),
            FractionStep(operation="subtract", numerator=1),
        ],
    )
    output_path = tmp_path / "fraction_bar.mp4"

    result_path = render_scene_to_mp4(TemplateName.FRACTION_BAR, params, output_path)

    assert result_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0
