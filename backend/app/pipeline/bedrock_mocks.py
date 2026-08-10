"""Canned Bedrock responses for the E2E happy-path smoke.

Enabled by setting the environment variable ``MATH_ANIM_MOCK_BEDROCK=1``
on the backend process (``call_with_tool`` reads the flag on every call).
Used by the Playwright happy-path spec so it can drive
upload → candidates → UI without shipping AWS credentials into CI.

Adding a new tool: register a handler here, keyed by the tool name that
``call_with_tool``'s callers pass in ``tools=[...]``. Handlers that do
not match the caller's tool set raise, so a new pipeline stage cannot
silently pass through the mock — the E2E maintainer sees the failure
and either adds a fixture or takes the stage off the smoke path.

Not intended for pytest — those tests already patch ``call_with_tool``
at the boundary they need with ``unittest.mock.patch`` and get finer
control than an env-gated stub can provide.
"""

from __future__ import annotations

from typing import Callable

# Chosen to match the text in `chain_test_deck.pptx` slide 0 (the fixture
# the happy-path spec uploads); the discovery grounder tokenizes the
# excerpt and requires each token to appear in the source slide's tokens,
# so a mock excerpt that drifts from the real slide text fails grounding
# and the mock passes but the pipeline drops the candidate — a subtle bug
# the E2E would report as "candidate list stayed empty" with no clear
# signal. Keep this string in sync with `eval/generate_fixtures.py`.
_CHAIN_DECK_SLIDE_0 = (
    "A frog is sitting on 3. It jumps forward 4 spaces. Where does it land?"
)


def _report_candidates(_system_prompt: str, _user_message: str) -> dict:
    """One grounded candidate — enough for the UI to render the picklist."""
    return {
        "candidates": [
            {
                "source_excerpt": _CHAIN_DECK_SLIDE_0,
                "slide_index": 0,
                "one_line_summary": "Frog on 3 jumps forward 4",
            }
        ]
    }


# Tool-name → handler. Each handler receives (system_prompt, user_message)
# and returns the parsed tool input dict the real Bedrock response would
# have produced.
_HANDLERS: dict[str, Callable[[str, str], dict]] = {
    "report_candidates": _report_candidates,
}


def mock_call_with_tool(
    system_prompt: str,
    user_message: str,
    tools: list[dict],
) -> tuple[str, dict]:
    """Dispatch to a canned handler based on the tool the caller advertised.

    Only supports the discovery tool at the moment; other pipeline stages
    (extraction, classification, stated-answer) will land here as the E2E
    smoke grows. Each raises loudly until a fixture is added — silent
    passthrough would let the smoke report a false green.
    """
    for tool in tools:
        name = tool.get("name")
        handler = _HANDLERS.get(name)
        if handler is not None:
            return name, handler(system_prompt, user_message)
    advertised = sorted(tool.get("name", "?") for tool in tools)
    raise NotImplementedError(
        f"Bedrock mock has no canned response for any of: {advertised}. "
        f"Add a handler in app.pipeline.bedrock_mocks or unset "
        f"MATH_ANIM_MOCK_BEDROCK for this test run."
    )
