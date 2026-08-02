"""Episode-level and aggregate segment boundary metrics."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .boundaries import BoundaryMatch, match_boundaries, metric_values


def evaluate_episode(qwen: dict[str, Any], baseline: dict[str, Any], loose_tolerance: int) -> dict[str, Any]:
    if qwen["turn_numbers"] != baseline["turn_numbers"]:
        raise ValueError("Aligned episode has different ordered turn indexes")
    strict = _mode(qwen["boundaries"], baseline["boundaries"], 0)
    loose = _mode(qwen["boundaries"], baseline["boundaries"], loose_tolerance)
    delta = qwen["segment_count"] - baseline["segment_count"]
    return {
        "session_id": qwen["session_id"],
        "qwen_episode_id": qwen["episode_id"],
        "deepseek_episode_id": baseline["episode_id"],
        "start_turn": qwen["start_turn"],
        "end_turn": qwen["end_turn"],
        "turn_count": len(qwen["turn_numbers"]),
        "qwen_segment_count": qwen["segment_count"],
        "deepseek_segment_count": baseline["segment_count"],
        "segment_delta": delta,
        "qwen_boundaries": _boundary_display(qwen),
        "deepseek_boundaries": _boundary_display(baseline),
        "strict": strict,
        "loose": loose,
        "classification": _classify(strict, loose, delta),
        "qwen_turns": qwen["turns"],
        "deepseek_turns": baseline["turns"],
    }


def _mode(qwen: list[int], baseline: list[int], tolerance: int) -> dict[str, Any]:
    matches, fp, fn = match_boundaries(qwen, baseline, tolerance=tolerance)
    result = metric_values(len(matches), len(fp), len(fn))
    result.update({
        "tolerance": tolerance,
        "matches": [_match_dict(match) for match in matches],
        "qwen_unmatched_positions": fp,
        "deepseek_unmatched_positions": fn,
    })
    return result


def _match_dict(match: BoundaryMatch) -> dict[str, int]:
    return {
        "qwen_position": match.qwen_position,
        "deepseek_position": match.baseline_position,
        "offset_turns": match.offset,
    }


def _boundary_display(episode: dict[str, Any]) -> list[dict[str, int]]:
    return [{"position": index, "turn_index": episode["turn_numbers"][index]} for index in episode["boundaries"]]


def _classify(strict: dict[str, Any], loose: dict[str, Any], delta: int) -> str:
    if strict["fp"] == strict["fn"] == 0:
        return "strict_match"
    if loose["fp"] == loose["fn"] == 0:
        return "loose_only_match"
    if delta > 0:
        return "qwen_net_oversegmented"
    if delta < 0:
        return "qwen_net_undersegmented"
    return "same_count_boundary_misaligned"


def aggregate(episodes: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    total_tp = sum(item[mode]["tp"] for item in episodes)
    total_fp = sum(item[mode]["fp"] for item in episodes)
    total_fn = sum(item[mode]["fn"] for item in episodes)
    micro = metric_values(total_tp, total_fp, total_fn)
    if episodes:
        macro = {
            key: sum(item[mode][key] for item in episodes) / len(episodes)
            for key in ("precision", "recall", "f1")
        }
    else:
        macro = {"precision": None, "recall": None, "f1": None}
    return {"micro": micro, "macro": macro}


def classification_summary(episodes: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    counts = Counter(item["classification"] for item in episodes)
    total = len(episodes)
    return {
        key: {"count": count, "rate": count / total if total else 0.0}
        for key, count in sorted(counts.items())
    }
