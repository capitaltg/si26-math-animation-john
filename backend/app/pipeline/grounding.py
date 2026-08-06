import copy
import math
import re
from dataclasses import dataclass

_REL_TOL = 1e-9
_ABS_TOL = 1e-12

_BLANK_PLACEHOLDER_RE = re.compile(r"\[\s*blank\s*\]")
_GROUNDING_TOKEN_RE = re.compile(
    r"(?:(?<![\w.])-?\d+(?:[./]\d+)*|(?<![\w.])-?\.\d+)"
    r"|[^\W\d_]+(?:'[^\W\d_]+)*"
    r"|[^\s|:,.;!?'\"“”‘’…•–—]"
)


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


def params_derived_totals(params) -> list[tuple[str, list[str], str]]:
    """Derived-total declarations a template vouches for.

    A two-item ``(total_token, component_tokens)`` declaration retains the
    original addition semantics. A three-item declaration adds an explicit
    operation (currently ``"product"``) for multiplicative guards.

    A template opts in to the derived-total allowance by defining a
    ``grounding_derived_totals`` method. The default is empty, so templates that
    do not opt in get strict literal-only grounding.
    """
    hook = getattr(params, "grounding_derived_totals", None)
    if callable(hook):
        declarations = []
        for declaration in hook():
            if len(declaration) == 2:
                total, components = declaration
                operation = "sum"
            else:
                total, components, operation = declaration
            declarations.append((str(total), list(components), str(operation)))
        return declarations
    return []


@dataclass(frozen=True)
class Span:
    start: int  # char index in the NORMALIZED source text
    end: int    # exclusive


def _normalize_for_grounding(text: str) -> str:
    """Same normalization tokenize_for_grounding applies, exposed so
    span-building sees identical text. `[blank]` becomes a single space so
    character offsets stay stable across match sites.
    """
    normalized = text.casefold().replace("’", "'").replace("−", "-")
    return _BLANK_PLACEHOLDER_RE.sub(" ", normalized)


def tokenize_for_grounding(text: str) -> list[str]:
    return _GROUNDING_TOKEN_RE.findall(_normalize_for_grounding(text))


def _canonical_key(token: str) -> str:
    """Two tokens share a canonical key iff they represent the same value.

    Numeric tokens key on `_token_value(token)` stringified so `3`, `3.0`,
    `3/1`, and `.5 / 0.5 / 1/2` collide correctly. Word tokens (value is
    None) key on the raw normalized string so word-vs-word grounding stays
    string-identity as today.
    """
    value = _token_value(token)
    if value is None:
        return token
    return repr(value)


def _build_source_occurrences(source_text: str) -> dict[str, list[Span]]:
    """Canonical-key -> in-order source spans (against normalized text)."""
    normalized = _normalize_for_grounding(source_text)
    occurrences: dict[str, list[Span]] = {}
    for match in _GROUNDING_TOKEN_RE.finditer(normalized):
        key = _canonical_key(match.group())
        occurrences.setdefault(key, []).append(Span(match.start(), match.end()))
    return occurrences


def _consume_all(components: list[str], occurrences: dict[str, list[Span]]) -> bool:
    """Pop one span per component from ``occurrences``; return False on shortfall."""
    for component in components:
        spans = occurrences.get(_canonical_key(component))
        if not spans:
            return False
        spans.pop(0)
    return True


def check_params_grounded(params, source_text: str) -> list[str]:
    """Return the params number tokens that are not grounded in the source.

    A token is grounded when the source has an unconsumed occurrence of that
    value in the multiset built from `tokenize_for_grounding(source_text)`,
    or when a template declares it a derived total whose components are
    each grounded against an independent fresh copy of that multiset and
    whose numeric value equals the sum/product of the components. An empty
    return means fully grounded.
    """
    original_occurrences = _build_source_occurrences(source_text)
    consuming = copy.deepcopy(original_occurrences)

    tokens = params_number_tokens(params)
    ungrounded_pending: list[str] = []
    for token in tokens:
        spans = consuming.get(_canonical_key(token))
        if spans:
            spans.pop(0)
        else:
            ungrounded_pending.append(token)

    allowed_totals: set[str] = set()
    for total_token, components, operation in params_derived_totals(params):
        if not components:
            continue
        fresh = copy.deepcopy(original_occurrences)
        if not _consume_all(components, fresh):
            continue
        total_value = _token_value(total_token)
        component_values = [_token_value(component) for component in components]
        if total_value is None or any(value is None for value in component_values):
            continue
        if operation == "sum":
            derived_value = sum(component_values)
        elif operation == "product":
            derived_value = math.prod(component_values)
        else:
            continue
        if math.isclose(derived_value, total_value, rel_tol=_REL_TOL, abs_tol=_ABS_TOL):
            allowed_totals.add(_canonical_key(total_token))

    return [
        token
        for token in ungrounded_pending
        if _canonical_key(token) not in allowed_totals
    ]
