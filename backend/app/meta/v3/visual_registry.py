from typing import Protocol

from app.meta.v3.geometry import MeasuredVisual, TextMeasurer


class VisualFactory(Protocol):
    def __call__(self, *, spec, values, measurer: TextMeasurer) -> MeasuredVisual:
        raise NotImplementedError


class VisualRegistry:
    def __init__(self):
        self._factories = {}

    def register(self, kind, factory):
        if kind in self._factories:
            raise ValueError(f"duplicate visual kind {kind}")
        self._factories[kind] = factory

    def measure(self, spec, values, measurer):
        try:
            factory = self._factories[spec.kind]
        except KeyError as exc:
            raise ValueError(f"unknown semantic visual {spec.kind}") from exc
        return factory(spec=spec, values=values, measurer=measurer)
