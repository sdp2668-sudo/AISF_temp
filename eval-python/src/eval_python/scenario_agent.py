"""Scenario and optional subscene classification from Segment intent summaries."""

from __future__ import annotations

from typing import Any

from .metrics import call_metric
from .models import AgentError, ScenarioResult, StageResult
from .prompts import scenario_system_prompt
from .qwen_client import QwenClient
from .taxonomy import OTHER_BUSINESS, Taxonomy
from .tooling import assistant_message, function_tool, parse_tool_arguments, tool_calls, tool_response


def run_scenario_agent(
    client: QwenClient,
    taxonomy: Taxonomy,
    intent_summary: str,
    *,
    session_id: str,
    episode_id: str,
    segment_id: str,
    enable_subscene: bool,
    max_rounds: int,
) -> StageResult:
    businesses = [*taxonomy.businesses, OTHER_BUSINESS]
    tool_name = "submit_tag" if enable_subscene else "submit_business"
    properties: dict[str, Any] = {"业务": {"type": "string", "enum": businesses}}
    required = ["业务"]
    if enable_subscene:
        properties["子功能"] = {"type": "string"}
        required.append("子功能")
    tools = [function_tool(
        tool_name,
        "提交这段对话的业务-子功能分类。" if enable_subscene else "提交这段对话的业务分类。",
        properties,
        required,
    )]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": scenario_system_prompt(taxonomy, enable_subscene=enable_subscene)},
        {"role": "user", "content": intent_summary},
    ]
    metrics = []
    raw_responses: list[dict[str, Any]] = []

    for _ in range(max_rounds):
        chat = client.chat(messages, tools)
        metrics.append(call_metric(
            "scenario",
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
            if isinstance(call.get("function"), dict) and call["function"].get("name") == tool_name
        ]
        if not matching:
            messages.append({"role": "user", "content": f"必须调用 {tool_name} 提交分类结果。"})
            continue

        call = matching[0]
        params = parse_tool_arguments(call)
        if params is None:
            messages.append(tool_response(call, {"ok": False, "errors": ["工具参数不是有效 JSON 对象"]}))
            continue
        business = params.get("业务")
        errors: list[str] = []
        if not isinstance(business, str) or business not in businesses:
            errors.append(f"业务必须是以下值之一: {'、'.join(businesses)}")

        if not enable_subscene:
            if errors:
                messages.append(tool_response(call, {"ok": False, "errors": errors}))
                continue
            assert isinstance(business, str)
            result = ScenarioResult(business, None, None, dict(params))
            return StageResult(result, tuple(metrics), tuple(raw_responses))

        sub_function = params.get("子功能")
        if not isinstance(sub_function, str) or not sub_function.strip():
            errors.append("子功能必须是非空字符串")
        elif isinstance(business, str) and business != OTHER_BUSINESS:
            valid_sub_functions = taxonomy.sub_functions(business)
            if sub_function not in valid_sub_functions:
                errors.append(
                    f'"{business}"下没有子功能"{sub_function}",合法子功能为: '
                    f"{'、'.join(valid_sub_functions)}",
                )
        if errors:
            messages.append(tool_response(call, {"ok": False, "errors": errors}))
            continue

        assert isinstance(business, str)
        assert isinstance(sub_function, str)
        result = ScenarioResult(
            business=business,
            sub_function=sub_function,
            is_control=False if business == OTHER_BUSINESS else taxonomy.is_control_pair(business, sub_function),
            raw=dict(params),
        )
        return StageResult(result, tuple(metrics), tuple(raw_responses))

    raise AgentError(
        f"Scenario Agent did not complete {session_id}/{episode_id}/{segment_id} "
        f"within {max_rounds} rounds",
    )

