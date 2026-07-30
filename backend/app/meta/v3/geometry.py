from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping
from typing import Protocol


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Bounds:
    left: float
    right: float
    bottom: float
    top: float

    @property
    def center(self) -> Point:
        return Point((self.left + self.right) / 2, (self.bottom + self.top) / 2)


@dataclass(frozen=True)
class SemanticPart:
    part: str
    index: int | None
    bounds: Bounds


@dataclass(frozen=True)
class MeasuredVisual:
    ref: str
    bounds: Bounds
    parts: Mapping[tuple[str, int | None], SemanticPart]
    paths: Mapping[str, tuple[Point, ...]]
    payload: object

    def __post_init__(self):
        object.__setattr__(self, "parts", MappingProxyType(dict(self.parts)))
        object.__setattr__(
            self,
            "paths",
            MappingProxyType({name: tuple(points) for name, points in self.paths.items()}),
        )

    def anchor(self, *, part: str | None, index: int | None, name: str) -> Point:
        bounds = self.bounds if part is None else self.parts[(part, index)].bounds
        return {
            "center": bounds.center,
            "top": Point(bounds.center.x, bounds.top),
            "bottom": Point(bounds.center.x, bounds.bottom),
            "left": Point(bounds.left, bounds.center.y),
            "right": Point(bounds.right, bounds.center.y),
        }[name]


class TextMeasurer(Protocol):
    def measure(self, text: str, font_role: str) -> tuple[float, float]:
        raise NotImplementedError
