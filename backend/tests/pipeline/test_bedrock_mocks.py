"""Bedrock mock is inert unless MATH_ANIM_MOCK_BEDROCK is truthy.

The mock is a boundary shim that only exists to make the browser-level
happy-path smoke deterministic without shipping AWS credentials to CI.
Everything below is about not paying for that convenience elsewhere:
the mock must be off by default, on only for the exact env value the
E2E workflow sets, and must fail loudly on any tool the smoke has not
yet supplied a fixture for.
"""

import pytest

from app.pipeline.bedrock_client import _mock_enabled
from app.pipeline.bedrock_mocks import mock_call_with_tool


def test_mock_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MATH_ANIM_MOCK_BEDROCK", raising=False)
    assert _mock_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
def test_mock_enabled_by_truthy_env_values(monkeypatch, value):
    monkeypatch.setenv("MATH_ANIM_MOCK_BEDROCK", value)
    assert _mock_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", ""])
def test_mock_not_enabled_by_falsy_env_values(monkeypatch, value):
    monkeypatch.setenv("MATH_ANIM_MOCK_BEDROCK", value)
    assert _mock_enabled() is False


def test_mock_returns_grounded_discovery_response():
    tools = [{"name": "report_candidates", "schema": {}}]
    name, result = mock_call_with_tool("sys", "user", tools)
    assert name == "report_candidates"
    # The E2E fixture (chain_test_deck.pptx) requires the returned excerpt
    # to token-match slide 0 for grounding to accept it. If someone
    # changes either the fixture or the mock excerpt, this catches the
    # drift before the browser test does.
    assert result["candidates"], "mock must return at least one candidate"
    excerpt = result["candidates"][0]["source_excerpt"]
    assert "frog" in excerpt.lower() and "3" in excerpt and "4" in excerpt


def test_mock_raises_on_unknown_tool_name():
    """Silent passthrough would let the E2E green on a false positive.

    A new pipeline stage that calls Bedrock with a tool the mock does not
    know about must fail visibly in the smoke run, not fall back to real
    Bedrock (there are no creds) and not return an empty envelope.
    """
    tools = [{"name": "extract_something_new", "schema": {}}]
    with pytest.raises(NotImplementedError, match="extract_something_new"):
        mock_call_with_tool("sys", "user", tools)
