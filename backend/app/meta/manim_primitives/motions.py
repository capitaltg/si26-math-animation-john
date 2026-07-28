from manim import FadeIn, Indicate, MoveAlongPath, Transform


def build_appear(mobject):
    return FadeIn(mobject)


def build_highlight(mobject):
    return Indicate(mobject)


def build_transform(source_mobject, target_mobject):
    return Transform(source_mobject, target_mobject)


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
