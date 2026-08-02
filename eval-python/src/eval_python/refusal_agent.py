"""Faithful Python port of AIsayno explicit unsupported detection."""

from __future__ import annotations

from typing import Any

from .metrics import call_metric
from .models import AgentError, RefusalFinding, RefusalResult, StageResult, Turn
from .prompts import REASON_MEDIA_UNAVAILABLE, REASON_NO_CAPABILITY, REFUSAL_SYSTEM_PROMPT
from .qwen_client import QwenClient
from .tooling import (
    assistant_message,
    function_tool,
    integer_value,
    parse_tool_arguments,
    tool_calls,
    tool_response,
)


HARD_FAIL = (
    "无法", "不能", "没办法", "不支持", "听不懂", "不太清楚", "不清楚", "没听清",
    "没听明白", "没明白", "不明白", "没找到", "找不到", "出错", "错误", "失败", "暂时不能",
    "目前不", "暂时无法", "无法理解", "听不清", "没听懂", "不知道", "不太明白", "具体指",
    "请详细", "您能详细", "详细说", "您能说",
)
REDIRECT_PLATFORMS = (
    "咪咕视频", "优酷视频", "腾讯视频", "哔哩哔哩", "b站", "B站", "快手", "抖音", "微博",
    "芒果tv", "芒果TV", "爱奇艺", "酷喵", "奇异果",
)
REDIRECT_ACTION_WORDS = ("可以", "前往", "搜索", "站内", "观看", "看", "搜")
ALLOWED_REASONS = (REASON_MEDIA_UNAVAILABLE, REASON_NO_CAPABILITY)


def run_refusal_agent(
    client: QwenClient,
    turns: tuple[Turn, ...],
    *,
    session_id: str,
    episode_id: str,
    segment_id: str,
    max_rounds: int,
) -> StageResult:
    judgeable = [turn.turn_no for turn in turns if turn.ai is not None]
    if not judgeable:
        return StageResult(
            RefusalResult("否", "", tuple(), {"findings": []}),
            (),
            (),
        )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": REFUSAL_SYSTEM_PROMPT},
        {"role": "user", "content": _format_segment_text(turns)},
    ]
    tools = [function_tool(
        "submit_findings",
        "提交这段对话里命中的所有 badcase 信号(原因1/原因2),没有命中时传入空数组。",
        {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "轮次": {"type": "integer", "enum": judgeable},
                        "判定原因": {"type": "string", "enum": list(ALLOWED_REASONS)},
                    },
                    "required": ["轮次", "判定原因"],
                    "additionalProperties": False,
                },
            },
        },
        ["findings"],
    )]
    metrics = []
    raw_responses: list[dict[str, Any]] = []

    for _ in range(max_rounds):
        chat = client.chat(messages, tools)
        metrics.append(call_metric(
            "ai_unsupported",
            chat,
            session_id=session_id,
            episode_id=episode_id,
            segment_id=segment_id,
        ))
        if chat.raw_response is not None:
            raw_responses.append(chat.raw_response)
        messages.append(assistant_message(chat.message))
        matching = [
            call for call in tool_calls(chat.message)
            if isinstance(call.get("function"), dict)
            and call["function"].get("name") == "submit_findings"
        ]
        if not matching:
            messages.append({
                "role": "user",
                "content": "必须调用 submit_findings;没有命中也提交空数组。",
            })
            continue

        call = matching[0]
        params = parse_tool_arguments(call)
        if params is None:
            messages.append(tool_response(call, {"ok": False, "errors": ["工具参数不是有效 JSON 对象"]}))
            continue
        raw_findings = params.get("findings")
        errors: list[str] = []
        findings: list[RefusalFinding] = []
        seen: set[int] = set()
        if not isinstance(raw_findings, list):
            errors.append("findings 必须是数组")
        else:
            for index, raw in enumerate(raw_findings):
                if not isinstance(raw, dict):
                    errors.append(f"findings[{index}] 必须是对象")
                    continue
                turn_no = integer_value(raw.get("轮次"))
                reason = raw.get("判定原因")
                if turn_no is None or turn_no not in judgeable:
                    errors.append(f"findings[{index}].轮次不是有助手回复的合法轮次")
                    continue
                if turn_no in seen:
                    errors.append(f"轮次 {turn_no} 重复提交")
                    continue
                seen.add(turn_no)
                if reason not in ALLOWED_REASONS:
                    errors.append(f"findings[{index}].判定原因不合法")
                    continue
                findings.append(RefusalFinding(turn_no, reason))
        if errors:
            messages.append(tool_response(call, {"ok": False, "errors": errors}))
            continue

        reasons = list(dict.fromkeys(finding.reason for finding in findings))
        result = RefusalResult(
            ai_unsupported="是" if findings else "否",
            judgment_reason="；".join(reasons),
            findings=tuple(findings),
            raw=dict(params),
        )
        return StageResult(result, tuple(metrics), tuple(raw_responses))

    raise AgentError(
        f"Refusal Agent did not complete {session_id}/{episode_id}/{segment_id} "
        f"within {max_rounds} rounds",
    )


def _format_segment_text(turns: tuple[Turn, ...]) -> str:
    rows: list[str] = []
    for turn in turns:
        assistant = turn.ai
        hard_fail = assistant is not None and any(word in assistant for word in HARD_FAIL)
        redirect = (
            assistant is not None
            and any(platform in assistant for platform in REDIRECT_PLATFORMS)
            and any(word in assistant for word in REDIRECT_ACTION_WORDS)
        )
        hints = []
        if hard_fail:
            hints.append("疑似硬失败")
        if redirect:
            hints.append("疑似转介")
        hint_text = f"[提示:{'/'.join(hints)}]" if hints else ""
        rows.append(
            f"[轮次 {turn.turn_no}]{hint_text} 用户: {turn.human}\n"
            f"助手: {assistant if assistant is not None else '(空)'}",
        )
    return "\n\n".join(rows)

