from app.models.scene import TemplateName
from app.render.full_render import render_scene_to_mp4
from app.templates.balance_scale.params import BalanceScaleParams


def test_balance_scale_renders_to_mp4(tmp_path):
    params = BalanceScaleParams(left_terms=[3, 4], right_total=7)
    output_path = tmp_path / "balance_scale.mp4"

    result_path = render_scene_to_mp4(TemplateName.BALANCE_SCALE, params, output_path)

    assert result_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0
