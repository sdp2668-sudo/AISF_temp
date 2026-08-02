"""Shared conversion from model responses to exportable call metrics."""

from __future__ import annotations

from .models import CallMetric, ChatResult


def call_metric(
    stage: str,
    result: ChatResult,
    *,
    session_id: str,
    episode_id: str = "",
    segment_id: str = "",
) -> CallMetric:
    return CallMetric(
        stage=stage,
        elapsed_seconds=result.elapsed_seconds,
        attempts=result.attempts,
        session_id=session_id,
        episode_id=episode_id,
        segment_id=segment_id,
        prompt_tokens=result.usage.get("prompt_tokens", 0),
        completion_tokens=result.usage.get("completion_tokens", 0),
        total_tokens=result.usage.get("total_tokens", 0),
    )

