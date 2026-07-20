from functools import lru_cache

import boto3

from app.config import get_settings


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


def call_with_tool(system_prompt: str, user_message: str, tool_name: str, tool_schema: dict) -> dict:
    settings = get_settings()
    client = get_bedrock_client()
    response = client.converse(
        modelId=settings.bedrock_model_id,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_message}]}],
        toolConfig={
            "tools": [{"toolSpec": {"name": tool_name, "inputSchema": {"json": tool_schema}}}],
            "toolChoice": {"tool": {"name": tool_name}},
        },
    )
    for block in response["output"]["message"]["content"]:
        if "toolUse" in block:
            return block["toolUse"]["input"]
    raise RuntimeError("Bedrock response did not include a tool call")
