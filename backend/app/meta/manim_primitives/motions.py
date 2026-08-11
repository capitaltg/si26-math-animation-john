from manim import FadeIn, Indicate, MoveAlongPath, Rotate, Transform, smooth


def build_appear(mobject):
    return FadeIn(mobject)


def build_highlight(mobject):
    return Indicate(mobject)


def build_transform(source_mobject, target_mobject):
    return Transform(source_mobject, target_mobject)


def build_role_transition(mobject, style: dict):
    target = mobject.copy()
    target.set_color(style["color"])
    target.set_stroke(width=style["stroke_width"])
    return Transform(mobject, target)


def build_move_along_path(mobject, path_mobject):
    return MoveAlongPath(mobject, path_mobject)


def build_camera_focus(scene, target_mobject, buffer: float = 1.0) -> None:
    frame = getattr(getattr(scene, "camera", None), "frame", None)
    if frame is None:
        raise TypeError(
            "build_camera_focus requires a MovingCameraScene (scene.camera.frame is missing)"
        )
    scene.play(frame.animate.move_to(target_mobject.get_center()).set(width=target_mobject.width + buffer))


def build_wait(scene, seconds: float) -> None:
    scene.wait(seconds)


def rotate_polygon(
    polygon_mobject,
    *,
    angle_rad: float,
    about_scene_point: tuple[float, float, float],
    run_time: float,
) -> Rotate:
    """One discrete rotation step for a polygon (M22).

    Wraps manim.Rotate with a smoothstep-like ease so a 90° step reads as a
    beat rather than a continuous spin. `about_scene_point` is a 3-tuple of
    scene-space coordinates (z=0). Caller sets `run_time` per iteration and
    lets a settle interval pass before the next step.
    """
    return Rotate(
        polygon_mobject,
        angle=angle_rad,
        about_point=about_scene_point,
        run_time=run_time,
        rate_func=smooth,
    )
