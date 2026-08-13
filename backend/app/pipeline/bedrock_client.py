import os
from functools import lru_cache

import boto3

from app.config import get_settings
from app.pipeline.bedrock_mocks import mock_call_with_tool
from app.quota import enforce_bedrock_quota

#: When set to a truthy value, ``call_with_tool`` short-circuits to a canned
#: response registry instead of calling Bedrock. Intended for browser-level
#: smoke tests that need a deterministic reply and cannot ship AWS creds
#: into CI. The stub raises loudly on any tool name it does not know about,
#: so silent drift is impossible — a new tool call added to the pipeline
#: forces the E2E fixture set to grow.
_MOCK_ENV_VAR = "MATH_ANIM_MOCK_BEDROCK"


def _mock_enabled() -> bool:
    return os.environ.get(_MOCK_ENV_VAR, "").lower() in {"1", "true", "yes"}


@lru_cache
def get_bedrock_client():
    settings = get_settings()
    client_kwargs = {"region_name": settings.aws_region}
    for setting_name, client_name in (
        ("aws_access_key_id", "aws_access_key_id"),
        ("aws_secret_access_key", "aws_secret_access_key"),
        ("aws_session_token", "aws_session_token"),
    ):
        value = getattr(settings, setting_name)
        if value:
            client_kwargs[client_name] = value
    return boto3.client("bedrock-runtime", **client_kwargs)


def call_with_tool(
    system_prompt: str,
    user_message: str,
    tools: list[dict],
) -> tuple[str, dict]:
    if _mock_enabled():
        return mock_call_with_tool(system_prompt, user_message, tools)
    # Kill switch + L2/L3 quota gate — raises BedrockDisabled or
    # BedrockQuotaExceeded before we spend an AWS call.
    enforce_bedrock_quota()
    settings = get_settings()
    client = get_bedrock_client()
    response = client.converse(
        modelId=settings.bedrock_model_id,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_message}]}],
        toolConfig={
            "tools": [
                {"toolSpec": {"name": tool["name"], "inputSchema": {"json": tool["schema"]}}}
                for tool in tools
            ],
            "toolChoice": {"any": {}},
        },
    )
    for block in response["output"]["message"]["content"]:
        if "toolUse" in block:
            return block["toolUse"]["name"], block["toolUse"]["input"]
    raise RuntimeError("Bedrock response did not include a tool call")
