"""OpenAI-compatible function-tool helpers shared by all agents."""

from __future__ import annotations

import json
from typing import Any

from .models import AgentError


def function_tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


def parse_tool_arguments(call: dict[str, Any]) -> dict[str, Any] | None:
    function = call.get("function")
    if not isinstance(function, dict):
        return None
    arguments = function.get("arguments", "{}")
    if isinstance(arguments, dict):
        return arguments
    if not isinstance(arguments, str):
        return None
    try:
        value = json.loads(arguments)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    calls = message.get("tool_calls", [])
    if calls is None:
        return []
    if not isinstance(calls, list) or any(not isinstance(call, dict) for call in calls):
        raise AgentError("Assistant message tool_calls must be an array of objects")
    return calls


def assistant_message(message: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"role": "assistant", "content": message.get("content") or ""}
    calls = message.get("tool_calls")
    if calls:
        result["tool_calls"] = calls
    return result


def tool_response(call: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    call_id = call.get("id")
    if not isinstance(call_id, str) or not call_id:
        raise AgentError("Tool call is missing an id")
    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps(value, ensure_ascii=False)}


def integer_value(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = int(value)
    return parsed if parsed == value else None

