from fractions import Fraction

from app.models.scene import Scene
from app.templates.registry import get_chained_template, get_template


def format_answer(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def compute_answer_for(scene: Scene) -> Fraction | None:
    if scene.template is None:
        return None
    if scene.candidate_ids:
        _, params_cls = get_chained_template(scene.template)
    else:
        _, params_cls = get_template(scene.template)
    try:
        params = params_cls.model_validate(scene.params)
    except Exception:
        return None
    return params.compute_answer()


def scene_mismatch(scene: Scene) -> dict | None:
    if scene.stated_answer is None:
        return None
    computed = compute_answer_for(scene)
    if computed is None:
        return None
    if computed == scene.stated_answer:
        return None
    return {
        "stated": format_answer(scene.stated_answer),
        "computed": format_answer(computed),
    }
