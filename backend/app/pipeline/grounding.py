import bisect
import copy
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

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


def params_string_tokens(params) -> list[str]:
    """Source-owned string/enum values a template declares via the hook.

    No generic default here (unlike numbers): a hand-written template's
    string/enum leaves are as likely to be internal contract fields (e.g. an
    `operation: Literal["add", "subtract"]`) as source-copied text, so
    blindly walking every string leaf would demand a literal source span for
    values that were never meant to appear in the problem text. Absent the
    hook, no string tokens are checked.
    """
    hook = getattr(params, "grounding_string_tokens", None)
    if callable(hook):
        return list(hook())
    return []


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


def _build_source_token_sequence(source_text: str) -> list[tuple[str, Span]]:
    """In-order (canonical_key, Span) pairs for every source token.

    Phrase grounding needs the ordered sequence — not just a multiset — so a
    source-owned string value binds to one contiguous run of source tokens
    rather than one token per value word chosen independently.
    """
    normalized = _normalize_for_grounding(source_text)
    return [
        (_canonical_key(match.group()), Span(match.start(), match.end()))
        for match in _GROUNDING_TOKEN_RE.finditer(normalized)
    ]


def _phrase_candidate_spans(
    phrase_keys: list[str], source_tokens: list[tuple[str, Span]]
) -> list[Span]:
    """Every source span whose consecutive tokens match `phrase_keys`, in
    source order.

    Matching is against normalized token boundaries the shared tokenizer
    produces, so "cat" cannot bind inside "concatenate" (one source token),
    and a two-word phrase like "red balloon" must appear as those two
    tokens in that order with no intervening tokens.
    """
    if not phrase_keys:
        return []
    n = len(phrase_keys)
    spans: list[Span] = []
    for start in range(len(source_tokens) - n + 1):
        window = source_tokens[start:start + n]
        if [key for key, _ in window] == phrase_keys:
            spans.append(Span(window[0][1].start, window[-1][1].end))
    return spans


# The interval DP's state is (span index, per-slot remaining capacities), so
# its size scales with Product(cap_i + 1). When every phrase is a distinct
# slot with cap 1, that product is 2^(distinct slots) and the solver stops
# being polynomial. The DSL contract does not cap the total number of
# source-owned string values a params object can emit (multiple arrays and
# top-level fields compose), so an adversarial-but-schema-valid input could
# push the solver past request-latency budgets. Above this threshold on
# distinct slots, we fall back to a length-descending greedy first-fit — it
# is not maximum-cardinality in every edge case, but it stays fast and still
# enforces ordered contiguous-span matching (the release-blocker fix). The
# threshold sits comfortably above real DSL usage; templates observed in
# fixtures declare at most a handful of distinct source-owned string values.
_PHRASE_SOLVER_MAX_DISTINCT_SLOTS = 12


def _greedy_phrase_assignment(
    phrases: list[list[str]], source_tokens: list[tuple[str, Span]]
) -> list[Span | None]:
    """Length-descending greedy first-fit fallback for the >12-slot path.

    Longer phrases get first pick over their limited candidate spans, so a
    two-word phrase whose only span coincides with a common single word
    keeps that span. Not optimal in every case, but bounded runtime.
    """
    n = len(phrases)
    result: list[Span | None] = [None] * n
    order = sorted(
        (i for i, keys in enumerate(phrases) if keys),
        key=lambda i: (-len(phrases[i]), i),
    )
    consumed: list[Span] = []
    for i in order:
        for span in _phrase_candidate_spans(phrases[i], source_tokens):
            if any(span.start < t.end and t.start < span.end for t in consumed):
                continue
            result[i] = span
            consumed.append(span)
            break
    return result


def _resolve_phrase_assignments(
    phrases: list[list[str]], source_tokens: list[tuple[str, Span]]
) -> list[Span | None]:
    """Assign each phrase to a non-overlapping source span if possible;
    return one span per phrase (None where no assignment grounds it).

    Greedy claim-first-match wrongly rejects fully-groundable inputs when
    phrases share tokens: for ["red", "red balloon"] against
    "red balloon red", giving "red" the first source "red" would strand
    "red balloon" without adjacent tokens even though assigning "red
    balloon" to the first two source tokens and "red" to the last one
    grounds both.

    Instead, collapse identical phrase-key sequences into slots with
    per-slot capacities (so 12 identical values collapse to one slot cap
    12 rather than blowing up the search) and run an interval-scheduling
    DP over candidate spans sorted by end. State is (span index,
    remaining-capacity tuple); transitions decide take/skip. Above
    ``_PHRASE_SOLVER_MAX_DISTINCT_SLOTS`` distinct slots, fall back to a
    length-descending greedy so an adversarially large params object
    cannot drag the exponential worst case onto the request path.
    """
    n = len(phrases)
    result: list[Span | None] = [None] * n
    if n == 0:
        return result

    active_indices = [i for i, keys in enumerate(phrases) if keys]
    if not active_indices:
        return result

    active_keys = [tuple(phrases[i]) for i in active_indices]
    counter = Counter(active_keys)
    distinct_keys = list(counter.keys())

    if len(distinct_keys) > _PHRASE_SOLVER_MAX_DISTINCT_SLOTS:
        return _greedy_phrase_assignment(phrases, source_tokens)

    slot_of_key = {key: slot for slot, key in enumerate(distinct_keys)}
    capacities = tuple(counter[key] for key in distinct_keys)

    entries: list[tuple[Span, int]] = []
    for slot, keys in enumerate(distinct_keys):
        for span in _phrase_candidate_spans(list(keys), source_tokens):
            entries.append((span, slot))
    if not entries:
        return result

    entries.sort(key=lambda item: (item[0].end, item[0].start))
    ends_only = [span.end for span, _ in entries]

    # p[i] = largest j < i with entries[j].span.end <= entries[i].span.start;
    # -1 if none. Interval scheduling's "last compatible before i".
    predecessors = [
        bisect.bisect_right(ends_only, span.start) - 1
        for span, _ in entries
    ]

    entry_count = len(entries)

    @lru_cache(maxsize=None)
    def dp(last: int, caps: tuple[int, ...]) -> int:
        if last < 0:
            return 0
        _, slot = entries[last]
        skip_value = dp(last - 1, caps)
        take_value = -1
        if caps[slot] > 0:
            reduced = caps[:slot] + (caps[slot] - 1,) + caps[slot + 1:]
            take_value = 1 + dp(predecessors[last], reduced)
        return skip_value if skip_value > take_value else take_value

    dp(entry_count - 1, capacities)

    # Reconstruct the chosen (span, slot) pairs. On ties (take_value ==
    # skip_value) prefer taking, so a phrase whose only valid span is here
    # keeps that span instead of ceding it to a still-optional phrase later.
    chosen: list[tuple[Span, int]] = []
    caps_state = list(capacities)
    i = entry_count - 1
    while i >= 0:
        span, slot = entries[i]
        skip_value = dp(i - 1, tuple(caps_state))
        take_value = -1
        if caps_state[slot] > 0:
            reduced = tuple(
                caps_state[k] - (1 if k == slot else 0) for k in range(len(caps_state))
            )
            take_value = 1 + dp(predecessors[i], reduced)
        if take_value >= skip_value and take_value >= 0:
            chosen.append((span, slot))
            caps_state[slot] -= 1
            i = predecessors[i]
        else:
            i -= 1

    dp.cache_clear()

    spans_by_slot: dict[int, list[Span]] = {}
    for span, slot in chosen:
        spans_by_slot.setdefault(slot, []).append(span)

    for phrase_pos, phrase_index in enumerate(active_indices):
        slot = slot_of_key[active_keys[phrase_pos]]
        available = spans_by_slot.get(slot)
        if available:
            result[phrase_index] = available.pop()
    return result


def _consume_all(components: list[str], occurrences: dict[str, list[Span]]) -> bool:
    """Pop one span per component from ``occurrences``; return False on shortfall."""
    for component in components:
        spans = occurrences.get(_canonical_key(component))
        if not spans:
            return False
        spans.pop(0)
    return True


def check_params_grounded(params, source_text: str) -> list[str]:
    """Return the params number and source-owned string/enum tokens not grounded in the source.

    A token is grounded when the source has an unconsumed occurrence of that
    value in the multiset built from `tokenize_for_grounding(source_text)`,
    or, for a numeric token only, when a template declares it a derived total
    whose components are each grounded against an independent fresh copy of
    that multiset and whose numeric value equals the sum/product of the
    components. Derived-total allowance never applies to string/enum tokens,
    even when one coincidentally shares a canonical key with an allowed
    numeric total. An empty return means fully grounded.
    """
    original_occurrences = _build_source_occurrences(source_text)
    consuming = copy.deepcopy(original_occurrences)

    def consume(tokens: list[str]) -> list[str]:
        pending: list[str] = []
        for token in tokens:
            spans = consuming.get(_canonical_key(token))
            if spans:
                spans.pop(0)
            else:
                pending.append(token)
        return pending

    # Numeric tokens still bind through a shared source multiset so
    # derived-total allowance below can exempt them; string values now bind
    # to ordered contiguous source spans so a multi-word value like "red
    # balloon" requires the exact phrase, not two independent word matches.
    # Derived-total allowance must never exempt a source-owned string/enum
    # value merely because it shares a canonical key with an allowed numeric
    # total (e.g. a string field whose value is literally "7" is not vouched
    # for by an unrelated 3 + 4 = 7 total).
    ungrounded_numbers = consume(params_number_tokens(params))

    source_tokens = _build_source_token_sequence(source_text)
    string_values = list(params_string_tokens(params))
    phrase_keys_per_value = [
        [_canonical_key(token) for token in tokenize_for_grounding(value)]
        for value in string_values
    ]
    # An empty-after-normalization value (whitespace or punctuation only)
    # has nothing to bind against and is silently accepted, the same way the
    # prior word-multiset code accepted it. Filter those out before the
    # solver so the assignment is over real phrases only.
    active_indices = [i for i, keys in enumerate(phrase_keys_per_value) if keys]
    active_phrase_keys = [phrase_keys_per_value[i] for i in active_indices]
    assignments = _resolve_phrase_assignments(active_phrase_keys, source_tokens)
    ungrounded_strings: list[str] = [
        string_values[active_indices[i]]
        for i, span in enumerate(assignments)
        if span is None
    ]

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
        for token in ungrounded_numbers
        if _canonical_key(token) not in allowed_totals
    ] + ungrounded_strings
