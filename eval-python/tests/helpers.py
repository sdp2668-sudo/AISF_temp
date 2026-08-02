from __future__ import annotations

import copy
import json
from typing import Any

from eval_python.models import ChatResult


def tool_message(name: str, arguments: dict[str, Any], call_id: str = "call-1") -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
        }],
    }


class ScriptedClient:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = list(messages)
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, tools=None):
        self.calls.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)})
        if not self.messages:
            raise AssertionError("Unexpected model call")
        message = self.messages.pop(0)
        return ChatResult(
            message=message,
            usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            elapsed_seconds=0.01,
            attempts=1,
            raw_response={"choices": [{"message": message}]},
        )


class RoutingClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def chat(self, messages, tools=None):
        names = [tool["function"]["name"] for tool in tools or []]
        if "add_segment" in names:
            total = _total_turns_from_prompt(messages[0]["content"])
            message = tool_message("add_segment", {
                "endTurn": total,
                "intentSummary": "测试意图",
                "noiseTurns": [],
            })
            stage = "segmentation"
        elif "submit_tag" in names:
            message = tool_message("submit_tag", {"业务": "语音对话", "子功能": "闲聊"})
            stage = "scenario"
        elif "submit_business" in names:
            message = tool_message("submit_business", {"业务": "语音对话"})
            stage = "scenario"
        elif "submit_findings" in names:
            message = tool_message("submit_findings", {"findings": []})
            stage = "ai_unsupported"
        else:
            raise AssertionError(f"Unknown tool set: {names}")
        self.calls.append(stage)
        return ChatResult(
            message=message,
            usage={"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
            elapsed_seconds=0.02,
            attempts=1,
            raw_response={"choices": [{"message": message}]},
        )


def _total_turns_from_prompt(prompt: str) -> int:
    marker = "对话总共有 "
    start = prompt.index(marker) + len(marker)
    end = prompt.index(" 轮", start)
    return int(prompt[start:end])

