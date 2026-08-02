"""Read successful episode-level segmentation from a Qwen run artifact."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .boundaries import boundaries_from_segment_labels


def load_qwen_run(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve()
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Unable to read Qwen JSON {source}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid Qwen JSON {source}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("sessions"), list):
        raise ValueError("Qwen JSON must contain a sessions array")
    return data


def qwen_episodes(run: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    successful: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for session in run["sessions"]:
        session_id = str(session.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("Qwen JSON contains a session with empty session_id")
        status = session.get("status")
        if status in {"failed", "filtered"}:
            excluded.append({"session_id": session_id, "episode_id": None, "reason": f"session_{status}"})
            continue
        for episode in session.get("episodes", []):
            if episode.get("status") != "succeeded":
                excluded.append({"session_id": session_id, "episode_id": episode.get("episode_id"), "reason": f"episode_{episode.get('status', 'unknown')}"})
                continue
            turns = []
            for segment in episode.get("segments", []):
                segment_id = str(segment.get("segment_id") or "").strip()
                if not segment_id:
                    raise ValueError(f"Qwen {session_id}/{episode.get('episode_id')} has empty segment_id")
                for turn in segment.get("turns", []):
                    turns.append({
                        "session_id": session_id,
                        "episode_id": str(episode.get("episode_id") or ""),
                        "segment_id": segment_id,
                        "turn_index": int(turn["turn_no"]),
                        "human": turn.get("human"),
                        "ai": turn.get("ai"),
                        "time": turn.get("timestamp"),
                    })
            if not turns:
                raise ValueError(f"Qwen {session_id}/{episode.get('episode_id')} succeeded without turns")
            boundaries, turn_numbers = boundaries_from_segment_labels(turns)
            successful.append({
                "source": "qwen",
                "session_id": session_id,
                "episode_id": str(episode.get("episode_id") or ""),
                "start_turn": turn_numbers[0],
                "end_turn": turn_numbers[-1],
                "turns": sorted(turns, key=lambda row: row["turn_index"]),
                "boundaries": boundaries,
                "turn_numbers": turn_numbers,
                "segment_count": len(boundaries) + 1,
            })
    return successful, excluded


def run_observability(run: dict[str, Any], excluded: list[dict[str, Any]]) -> dict[str, Any]:
    summary = run.get("summary") or {}
    return {
        "qwen_run_summary": summary,
        "qwen_errors": run.get("errors") or [],
        "successful_episodes_observed": summary.get("episodes"),
        "filtered_episodes_observed": summary.get("episodes_filtered"),
        "failed_sessions_observed": summary.get("sessions_failed"),
        "excluded_items": excluded,
        "limitation": "The Qwen run artifact preserves failed sessions but does not reliably preserve every failed episode, so failed episode count is not inferred.",
    }
