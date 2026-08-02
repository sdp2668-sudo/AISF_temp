"""Align successful Qwen episodes to DeepSeek reference episodes."""

from __future__ import annotations

from typing import Any

from .metrics import evaluate_episode


def align_and_evaluate(
    qwen_episodes: list[dict[str, Any]],
    deepseek_episodes: list[dict[str, Any]],
    loose_tolerance: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    qwen_map = {_key(item): item for item in qwen_episodes}
    baseline_map = {_key(item): item for item in deepseek_episodes}
    if len(qwen_map) != len(qwen_episodes) or len(baseline_map) != len(deepseek_episodes):
        raise ValueError("Duplicate episode alignment key")
    comparable = []
    excluded = []
    for key in sorted(set(qwen_map) | set(baseline_map)):
        qwen = qwen_map.get(key)
        baseline = baseline_map.get(key)
        if qwen is None:
            excluded.append(_excluded(baseline, "missing_qwen_episode"))
        elif baseline is None:
            excluded.append(_excluded(qwen, "missing_deepseek_episode"))
        else:
            comparable.append(evaluate_episode(qwen, baseline, loose_tolerance))
    return comparable, excluded


def _key(episode: dict[str, Any]) -> tuple[str, int, int]:
    return episode["session_id"], episode["start_turn"], episode["end_turn"]


def _excluded(episode: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "session_id": episode["session_id"],
        "episode_id": episode["episode_id"],
        "start_turn": episode["start_turn"],
        "end_turn": episode["end_turn"],
        "reason": reason,
    }
