import math
import re

_REL_TOL = 1e-9
_ABS_TOL = 1e-12

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


def params_derived_totals(params) -> list[tuple[str, list[str]]]:
    """(total_token, [component_tokens]) pairs a template vouches for.

    A template opts in to the derived-total allowance by defining a
    ``grounding_derived_totals`` method. The default is empty, so templates that
    do not opt in get strict literal-only grounding.
    """
    hook = getattr(params, "grounding_derived_totals", None)
    if callable(hook):
        return [(str(total), list(components)) for total, components in hook()]
    return []


def check_params_grounded(params, source_text: str) -> list[str]:
    """Return the params number tokens that are not grounded in the source.

    A token is grounded when it appears literally in the source tokens, or a
    template declared it a derived total (see ``grounding_derived_totals``) whose
    named components are all grounded literally and whose numeric value equals
    their sum. An empty return means fully grounded.
    """
    source = set(tokenize_for_grounding(source_text))
    tokens = params_number_tokens(params)
    grounded = {token for token in tokens if token in source}

    allowed_totals: set[str] = set()
    for total_token, components in params_derived_totals(params):
        if not components or any(component not in source for component in components):
            continue
        total_value = _token_value(total_token)
        component_values = [_token_value(component) for component in components]
        if total_value is None or any(value is None for value in component_values):
            continue
        if math.isclose(
            sum(component_values), total_value, rel_tol=_REL_TOL, abs_tol=_ABS_TOL
        ):
            allowed_totals.add(total_token)

    return [
        token
        for token in tokens
        if token not in grounded and token not in allowed_totals
    ]
