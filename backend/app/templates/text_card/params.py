from pydantic import BaseModel, Field, model_validator

from app.templates.text_card.guard import check_text_card_compatibility


class TextCardParams(BaseModel):
    headline: str
    lines: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_guard(self):
        check_text_card_compatibility(self)
        return self
