from dataclasses import dataclass


@dataclass(frozen=True)
class V3Failure:
    code: str
    path: str
    expected: str
    observed: str
    hint: str


class V3ValidationError(ValueError):
    def __init__(self, failure: V3Failure):
        super().__init__(f"{failure.code} at {failure.path}: {failure.observed}")
        self.failure = failure
