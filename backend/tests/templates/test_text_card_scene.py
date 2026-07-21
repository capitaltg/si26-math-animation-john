from app.models.scene import TemplateName
from app.render.full_render import render_scene_to_mp4
from app.templates.text_card.params import TextCardParams


def test_text_card_renders_to_mp4(tmp_path):
    params = TextCardParams(
        headline="Detected: 3 + 4",
        lines=["Slide 2: 3 + 4", "Fell back to a text card."],
    )
    output_path = tmp_path / "text_card.mp4"

    result_path = render_scene_to_mp4(TemplateName.TEXT_CARD, params, output_path)

    assert result_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0
