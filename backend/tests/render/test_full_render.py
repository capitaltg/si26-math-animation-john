from app.models.scene import TemplateName
from app.render.full_render import render_scene_thumbnail, render_scene_to_mp4
from app.templates.array_grid.params import ArrayGridParams
from app.templates.number_line.params import NumberLineParams, NumberLineStep


def test_render_number_line_scene_produces_mp4(tmp_path):
    params = NumberLineParams(start=2, steps=[NumberLineStep(operation="add", amount=3)])
    output_path = tmp_path / "scene.mp4"

    result_path = render_scene_to_mp4(TemplateName.NUMBER_LINE, params, output_path)

    assert result_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_render_array_grid_scene_produces_thumbnail(tmp_path):
    params = ArrayGridParams(rows=2, cols=3)
    output_path = tmp_path / "thumb.png"

    result_path = render_scene_thumbnail(TemplateName.ARRAY_GRID, params, output_path)

    assert result_path == output_path
    assert output_path.exists()
    assert output_path.suffix == ".png"
    assert output_path.stat().st_size > 0
