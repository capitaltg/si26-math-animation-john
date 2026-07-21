from app.models.scene import TemplateName
from app.render.full_render import render_scene_to_mp4
from app.templates.fraction_of_whole.params import FractionOfWholeParams


def test_fraction_of_whole_renders_to_mp4(tmp_path):
    params = FractionOfWholeParams(numerator=1, denominator=2)
    output_path = tmp_path / "fraction_of_whole.mp4"

    result_path = render_scene_to_mp4(TemplateName.FRACTION_OF_WHOLE, params, output_path)

    assert result_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0
