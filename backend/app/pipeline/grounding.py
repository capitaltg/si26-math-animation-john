import re

_BLANK_PLACEHOLDER_RE = re.compile(r"\[\s*blank\s*\]")
_GROUNDING_TOKEN_RE = re.compile(
    r"(?:\d+(?:[./]\d+)*|\.\d+)"
    r"|[^\W\d_]+(?:'[^\W\d_]+)*"
    r"|[^\s|:,.;!?'\"“”‘’…•–—]"
)


def tokenize_for_grounding(text: str) -> list[str]:
    normalized = text.casefold().replace("’", "'")
    normalized = _BLANK_PLACEHOLDER_RE.sub(" ", normalized)
    return _GROUNDING_TOKEN_RE.findall(normalized)


def _token_value(token: str) -> float | None:
    if "/" in token:
        numerator, _, denominator = token.partition("/")
        try:
            return float(numerator) / float(denominator)
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return float(token)
    except ValueError:
        return None


def default_number_tokens(params) -> list[str]:
    """Stringify every numeric (int/float, excluding bool) leaf of the params object."""
    tokens: list[str] = []

    def walk(value):
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            tokens.append(str(value))
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(params.model_dump())
    return tokens


def params_number_tokens(params) -> list[str]:
    hook = getattr(params, "grounding_number_tokens", None)
    if callable(hook):
        return list(hook())
    return default_number_tokens(params)


def check_params_grounded(params, source_text: str) -> list[str]:
    """Return the params number tokens that are not grounded in the source.

    A token is grounded when it appears in the source tokens, or (derived-total
    allowance) its numeric value equals the sum of the numeric values of the tokens
    grounded by the first rule. An empty return means fully grounded.
    """
    source = set(tokenize_for_grounding(source_text))
    tokens = params_number_tokens(params)
    grounded = {token for token in tokens if token in source}
    base_sum = sum(
        value for token in grounded if (value := _token_value(token)) is not None
    )
    ungrounded: list[str] = []
    for token in tokens:
        if token in grounded:
            continue
        value = _token_value(token)
        if grounded and value is not None and value == base_sum:
            continue
        ungrounded.append(token)
    return ungrounded
