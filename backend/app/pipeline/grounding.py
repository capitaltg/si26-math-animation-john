import re

_BLANK_PLACEHOLDER_RE = re.compile(r"\[\s*blank\s*\]")
_GROUNDING_TOKEN_RE = re.compile(
    r"(?:\d+(?:[./]\d+)*|\.\d+)"
    r"|[^\W\d_]+(?:'[^\W\d_]+)*"
    r"|[^\s|:,.;!?'\"""''…•–—]"
)


def tokenize_for_grounding(text: str) -> list[str]:
    normalized = text.casefold().replace("'", "'")
    normalized = _BLANK_PLACEHOLDER_RE.sub(" ", normalized)
    return _GROUNDING_TOKEN_RE.findall(normalized)
