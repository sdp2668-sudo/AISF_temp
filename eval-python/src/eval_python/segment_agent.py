"""Faithful Python port of AIsayno agents/segment.ts."""

from __future__ import annotations

from typing import Any

from .episode import validate_segment_coverage
from .metrics import call_metric
from .models import AgentError, SegmentBoundary, StageResult, Turn
from .prompts import segment_system_prompt
from .qwen_client import QwenClient
from .tooling import (
    assistant_message,
    function_tool,
    integer_value,
    parse_tool_arguments,
    tool_calls,
    tool_response,
)


def run_segment_agent(
    client: QwenClient,
    turns: tuple[Turn, ...],
    *,
    session_id: str,
    episode_id: str,
    window_size: int,
    max_rounds: int,
) -> StageResult:
    total_turns = len(turns)
    current_position = 1
    revealed_up_to = min(window_size, total_turns)
    segments: list[SegmentBoundary] = []
    committed_noise_turns: list[int] = []
    metrics = []
    raw_responses: list[dict[str, Any]] = []

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": segment_system_prompt(total_turns, window_size)},
        {"role": "user", "content": _format_turns_range(turns, 1, revealed_up_to)},
    ]
    tools = [
        function_tool(
            "add_segment",
            "从当前进度游标开始,提交一个新的 segment,覆盖到 endTurn。当 endTurn 等于总轮次时自动完成整个切分。",
            {
                "endTurn": {"type": "number"},
                "intentSummary": {"type": "string"},
                "noiseTurns": {"type": "array", "items": {"type": "number"}},
            },
            ["endTurn", "intentSummary", "noiseTurns"],
        ),
        function_tool(
            "undo_last_segment",
            "撤销最近一次提交的 segment,回退进度游标以便重新划分。可连续调用以撤销多段。",
            {},
        ),
    ]

    for _ in range(max_rounds):
        chat = client.chat(messages, tools)
        metrics.append(call_metric(
            "segmentation", chat, session_id=session_id, episode_id=episode_id,
        ))
        if chat.raw_response is not None:
            raw_responses.append(chat.raw_response)
        messages.append(assistant_message(chat.message))
        calls = tool_calls(chat.message)
        if not calls:
            messages.append({
                "role": "user",
                "content": "必须调用 add_segment 或 undo_last_segment 提交切分结果,不要只输出文字。",
            })
            continue

        for call in calls:
            function = call.get("function")
            name = function.get("name") if isinstance(function, dict) else None
            params = parse_tool_arguments(call)
            if params is None:
                messages.append(tool_response(call, {"ok": False, "errors": ["工具参数不是有效 JSON 对象"]}))
                continue

            if name == "undo_last_segment":
                if not segments:
                    result = {"ok": False, "errors": ["没有可撤销的 segment"]}
                else:
                    last = segments.pop()
                    current_position = last.start_turn
                    committed_noise_turns = [
                        number for number in committed_noise_turns
                        if number < last.start_turn or number > last.end_turn
                    ]
                    result = {
                        "ok": True,
                        "message": (
                            f"已撤销 {last.segment_id}(第 {last.start_turn}-{last.end_turn} 轮),"
                            f"当前进度回退到第 {current_position} 轮"
                        ),
                    }
                messages.append(tool_response(call, result))
                continue

            if name != "add_segment":
                messages.append(tool_response(call, {"ok": False, "errors": [f"未知工具: {name}"]}))
                continue

            end_turn = integer_value(params.get("endTurn"))
            intent_summary = params.get("intentSummary")
            raw_noise = params.get("noiseTurns")
            errors: list[str] = []
            if end_turn is None:
                errors.append("endTurn 必须是整数")
            else:
                if end_turn < current_position:
                    errors.append(f"endTurn ({end_turn}) 不能小于当前进度游标 ({current_position})")
                if end_turn > total_turns:
                    errors.append(f"endTurn ({end_turn}) 超出总轮次 ({total_turns})")
                if end_turn > revealed_up_to:
                    errors.append(
                        f"endTurn ({end_turn}) 超出了目前已展现范围(第 1-{revealed_up_to} 轮)",
                    )
            if not isinstance(intent_summary, str) or not intent_summary.strip():
                errors.append("intentSummary 必须是非空字符串")
            noise_turns: list[int] = []
            if not isinstance(raw_noise, list):
                errors.append("noiseTurns 必须是数组")
            else:
                for raw_number in raw_noise:
                    number = integer_value(raw_number)
                    if number is None:
                        errors.append(f"noiseTurns 包含非整数: {raw_number}")
                        continue
                    noise_turns.append(number)
                    if end_turn is not None and (number < current_position or number > end_turn):
                        errors.append(
                            f"noiseTurns 中的轮次 {number} 超出本 segment 范围 "
                            f"[{current_position}, {end_turn}]",
                        )
            if errors:
                messages.append(tool_response(call, {"ok": False, "errors": errors}))
                continue

            assert end_turn is not None
            assert isinstance(intent_summary, str)
            segment = SegmentBoundary(
                segment_id=f"s{len(segments) + 1}",
                start_turn=current_position,
                end_turn=end_turn,
                intent_summary=intent_summary.strip(),
                noise_turns=tuple(noise_turns),
            )
            segments.append(segment)
            committed_noise_turns.extend(noise_turns)
            current_position = end_turn + 1

            if current_position > total_turns:
                messages.append(tool_response(call, {
                    "ok": True,
                    "complete": True,
                    "message": (
                        f"已提交 {segment.segment_id}(第 {segment.start_turn}-{segment.end_turn} 轮),"
                        f"已覆盖到总轮次 {total_turns},切分完成"
                    ),
                }))
                validate_segment_coverage(turns, segments)
                return StageResult(tuple(segments), tuple(metrics), tuple(raw_responses))

            target_revealed = min(total_turns, current_position + window_size - 1)
            newly_revealed = ""
            if target_revealed > revealed_up_to:
                newly_revealed = _format_turns_range(turns, revealed_up_to + 1, target_revealed)
                revealed_up_to = target_revealed
            messages.append(tool_response(call, {
                "ok": True,
                "current_position": current_position,
                "message": (
                    f"已提交 {segment.segment_id}(第 {segment.start_turn}-{segment.end_turn} 轮),"
                    f"下一段从第 {current_position} 轮开始"
                ),
                "newly_revealed": newly_revealed,
            }))

    raise AgentError(
        f"Segment Agent did not complete {session_id}/{episode_id} within {max_rounds} rounds",
    )


def _format_turns_range(turns: tuple[Turn, ...], from_turn: int, to_turn: int) -> str:
    return "\n".join(
        f"[轮次 {local_index}] 用户: {turns[local_index - 1].human}"
        for local_index in range(from_turn, to_turn + 1)
    )

