import pytest
from pydantic import ValidationError


def test_valid_text_card_passes():
    from app.templates.text_card.params import TextCardParams

    params = TextCardParams(headline="Detected: 3 + 4", lines=["3 + 4 on slide 2"])
    assert params.headline == "Detected: 3 + 4"


def test_blank_headline_is_rejected():
    from app.templates.text_card.params import TextCardParams

    with pytest.raises(ValidationError):
        TextCardParams(headline="   ", lines=["something"])


def test_empty_lines_list_is_rejected():
    from app.templates.text_card.params import TextCardParams

    with pytest.raises(ValidationError):
        TextCardParams(headline="Heading", lines=[])
