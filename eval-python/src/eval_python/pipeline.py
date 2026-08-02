"""Bounded staged orchestration for Session segmentation and enrichment."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION, SOURCE_BASELINE
from .config import AppConfig
from .episode import split_episodes
from .models import Episode, RefusalResult, RunAccumulator, ScenarioResult, SessionInput
from .qwen_client import QwenClient
from .refusal_agent import run_refusal_agent
from .scenario_agent import run_scenario_agent
from .segment_agent import run_segment_agent
from .taxonomy import Taxonomy


ClientFactory = Callable[[], QwenClient]
ProgressCallback = Callable[[str], None]


def run_pipeline(
    sessions: list[SessionInput],
    config: AppConfig,
    taxonomy: Taxonomy,
    *,
    input_file: str | Path,
    client_factory: ClientFactory | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    started_at = _utc_now()
    started = time.perf_counter()
    run_id = f"{started_at.replace(':', '').replace('-', '')}-{uuid.uuid4().hex[:8]}"
    accumulator = RunAccumulator()
    make_client = client_factory or _default_client_factory(config)

    _progress(progress, f"segmentation: {len(sessions)} sessions")
    ordered_results: list[dict[str, Any] | None] = [None] * len(sessions)
    with ThreadPoolExecutor(max_workers=config.pipeline.session_concurrency) as executor:
        futures: dict[Future, int] = {}
        for index, session in enumerate(sessions):
            if session.user_id in config.filters.excluded_user_ids:
                reason = "user_id matched filters.excluded_user_ids"
                ordered_results[index] = _filtered_session(session, reason)
                accumulator.filtered.append({
                    "kind": "session",
                    "session_id": session.session_id,
                    "user_id": session.user_id,
                    "reason": reason,
                })
                continue
            futures[executor.submit(
                _segment_session,
                session,
                config,
                make_client,
            )] = index

        for future in as_completed(futures):
            index = futures[future]
            session = sessions[index]
            try:
                result, metrics, filtered = future.result()
            except Exception as exc:
                error = _error_record("segmentation", session.session_id, exc)
                accumulator.errors.append(error)
                ordered_results[index] = _failed_session(session, error)
            else:
                ordered_results[index] = result
                accumulator.metrics.extend(metrics)
                accumulator.filtered.extend(filtered)

    session_results = [result for result in ordered_results if result is not None]
    segment_items = _segment_items(session_results)
    _progress(progress, f"scenario: {len(segment_items)} segments")
    _run_scenario_stage(segment_items, config, taxonomy, make_client, accumulator)

    if config.features.enable_ai_unsupported:
        _progress(progress, f"ai_unsupported: {len(segment_items)} segments")
        _run_refusal_stage(segment_items, config, make_client, accumulator)
    else:
        for item in segment_items:
            _apply_refusal(item["segment"], RefusalResult(None, None, None, None), ())

    _finalize_statuses(session_results, accumulator.metrics)
    completed_at = _utc_now()
    elapsed = round(time.perf_counter() - started, 6)
    metrics = sorted(
        accumulator.metrics,
        key=lambda metric: (
            metric.session_id,
            _ordinal(metric.episode_id),
            _ordinal(metric.segment_id),
            _stage_order(metric.stage),
        ),
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "source_baseline": SOURCE_BASELINE,
        "run_id": run_id,
        "input_file": str(Path(input_file).resolve()),
        "started_at": started_at,
        "completed_at": completed_at,
        "elapsed_seconds": elapsed,
        "model": {
            "endpoint": config.model.endpoint,
            "name": config.model.name,
            "temperature": config.model.temperature,
            "enable_thinking": config.model.enable_thinking,
        },
        "features": {
            "enable_subscene": config.features.enable_subscene,
            "enable_ai_unsupported": config.features.enable_ai_unsupported,
        },
        "filters": {
            "excluded_user_ids": list(config.filters.excluded_user_ids),
            "max_episode_turns": config.filters.max_episode_turns,
            "excluded_items": accumulator.filtered,
        },
        "summary": _summary(session_results, metrics, accumulator.errors),
        "metrics": [metric.to_dict() for metric in metrics],
        "errors": accumulator.errors,
        "sessions": session_results,
    }
    _progress(progress, f"complete: {result['summary']['segments']} segments in {elapsed:.3f}s")
    return result


def _default_client_factory(config: AppConfig) -> ClientFactory:
    return lambda: QwenClient(
        config.model,
        include_raw_response=config.output.include_raw_model_response,
    )


def _segment_session(
    session: SessionInput,
    config: AppConfig,
    make_client: ClientFactory,
) -> tuple[dict[str, Any], list, list[dict[str, Any]]]:
    started = time.perf_counter()
    metrics = []
    filtered: list[dict[str, Any]] = []
    output_episodes: list[dict[str, Any]] = []
    episodes = split_episodes(session.turns, config.pipeline.episode_gap_minutes)

    for episode in episodes:
        if (
            config.filters.max_episode_turns is not None
            and len(episode.turns) > config.filters.max_episode_turns
        ):
            reason = f"episode has {len(episode.turns)} turns, limit is {config.filters.max_episode_turns}"
            filtered.append({
                "kind": "episode",
                "session_id": session.session_id,
                "episode_id": episode.episode_id,
                "start_turn": episode.start_turn,
                "end_turn": episode.end_turn,
                "reason": reason,
            })
            output_episodes.append(_filtered_episode(episode, reason))
            continue

        stage = run_segment_agent(
            make_client(),
            episode.turns,
            session_id=session.session_id,
            episode_id=episode.episode_id,
            window_size=config.pipeline.segment_window_size,
            max_rounds=config.pipeline.max_agent_rounds,
        )
        metrics.extend(stage.metrics)
        output_segments = [
            _map_segment(episode, boundary, stage.raw_messages)
            for boundary in stage.value
        ]
        output_episodes.append({
            "episode_id": episode.episode_id,
            "status": "succeeded",
            "start_turn": episode.start_turn,
            "end_turn": episode.end_turn,
            "gap_before_minutes": episode.gap_before_minutes,
            "segments": output_segments,
            "model_output": {
                "segmentation_responses": list(stage.raw_messages),
            },
        })

    return ({
        "session_id": session.session_id,
        "user_id": session.user_id,
        "status": "segmented",
        "error": None,
        "turn_count": len(session.turns),
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "episodes": output_episodes,
    }, metrics, filtered)


def _map_segment(episode: Episode, boundary, raw_messages: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    selected = episode.turns[boundary.start_turn - 1:boundary.end_turn]
    original_noise = [episode.turns[index - 1].turn_no for index in boundary.noise_turns]
    return {
        "segment_id": boundary.segment_id,
        "status": "segmented",
        "errors": [],
        "start_turn": selected[0].turn_no,
        "end_turn": selected[-1].turn_no,
        "intent_summary": boundary.intent_summary,
        "noise_turns": original_noise,
        "business": None,
        "sub_function": None,
        "is_control": None,
        "ai_unsupported": None,
        "judgment_reason": None,
        "refusal_findings": None,
        "turns": [turn.to_dict() for turn in selected],
        "model_output": {
            "segmentation": boundary.to_dict(),
            "scenario": None,
            "refusal": None,
        },
    }


def _segment_items(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for session_index, session in enumerate(sessions):
        if session["status"] in {"failed", "filtered"}:
            continue
        for episode_index, episode in enumerate(session["episodes"]):
            if episode["status"] != "succeeded":
                continue
            for segment_index, segment in enumerate(episode["segments"]):
                items.append({
                    "order": (session_index, episode_index, segment_index),
                    "session": session,
                    "episode": episode,
                    "segment": segment,
                })
    return items


def _run_scenario_stage(
    items: list[dict[str, Any]],
    config: AppConfig,
    taxonomy: Taxonomy,
    make_client: ClientFactory,
    accumulator: RunAccumulator,
) -> None:
    with ThreadPoolExecutor(max_workers=config.pipeline.segment_concurrency) as executor:
        futures = {
            executor.submit(
                run_scenario_agent,
                make_client(),
                taxonomy,
                item["segment"]["intent_summary"],
                session_id=item["session"]["session_id"],
                episode_id=item["episode"]["episode_id"],
                segment_id=item["segment"]["segment_id"],
                enable_subscene=config.features.enable_subscene,
                max_rounds=config.pipeline.max_agent_rounds,
            ): item
            for item in items
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                stage = future.result()
            except Exception as exc:
                error = _error_record(
                    "scenario",
                    item["session"]["session_id"],
                    exc,
                    item["episode"]["episode_id"],
                    item["segment"]["segment_id"],
                )
                item["segment"]["errors"].append(error)
                accumulator.errors.append(error)
            else:
                _apply_scenario(item["segment"], stage.value, stage.raw_messages)
                accumulator.metrics.extend(stage.metrics)


def _run_refusal_stage(
    items: list[dict[str, Any]],
    config: AppConfig,
    make_client: ClientFactory,
    accumulator: RunAccumulator,
) -> None:
    with ThreadPoolExecutor(max_workers=config.pipeline.segment_concurrency) as executor:
        futures = {
            executor.submit(
                run_refusal_agent,
                make_client(),
                tuple(_turn_from_dict(turn) for turn in item["segment"]["turns"]),
                session_id=item["session"]["session_id"],
                episode_id=item["episode"]["episode_id"],
                segment_id=item["segment"]["segment_id"],
                max_rounds=config.pipeline.max_agent_rounds,
            ): item
            for item in items
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                stage = future.result()
            except Exception as exc:
                error = _error_record(
                    "ai_unsupported",
                    item["session"]["session_id"],
                    exc,
                    item["episode"]["episode_id"],
                    item["segment"]["segment_id"],
                )
                item["segment"]["errors"].append(error)
                accumulator.errors.append(error)
            else:
                _apply_refusal(item["segment"], stage.value, stage.raw_messages)
                accumulator.metrics.extend(stage.metrics)


def _apply_scenario(
    segment: dict[str, Any],
    result: ScenarioResult,
    raw_messages: tuple[dict[str, Any], ...],
) -> None:
    segment["business"] = result.business
    segment["sub_function"] = result.sub_function
    segment["is_control"] = result.is_control
    segment["model_output"]["scenario"] = {
        "submitted": result.raw,
        "responses": list(raw_messages),
    }


def _apply_refusal(
    segment: dict[str, Any],
    result: RefusalResult,
    raw_messages: tuple[dict[str, Any], ...],
) -> None:
    segment["ai_unsupported"] = result.ai_unsupported
    segment["judgment_reason"] = result.judgment_reason
    segment["refusal_findings"] = (
        None if result.findings is None else [finding.to_dict() for finding in result.findings]
    )
    segment["model_output"]["refusal"] = (
        None if result.findings is None else {
            "submitted": result.raw,
            "responses": list(raw_messages),
        }
    )


def _finalize_statuses(sessions: list[dict[str, Any]], metrics: list) -> None:
    for session in sessions:
        if session["status"] in {"failed", "filtered"}:
            continue
        segments = [
            segment
            for episode in session["episodes"]
            for segment in episode.get("segments", [])
        ]
        for segment in segments:
            segment["status"] = "failed" if segment["errors"] else "succeeded"
        session["status"] = "partial_failed" if any(segment["errors"] for segment in segments) else "succeeded"
        session_metrics = [metric for metric in metrics if metric.session_id == session["session_id"]]
        session["model_calls"] = len(session_metrics)
        session["model_elapsed_seconds"] = round(
            sum(metric.elapsed_seconds for metric in session_metrics), 6,
        )


def _summary(sessions: list[dict[str, Any]], metrics: list, errors: list[dict[str, Any]]) -> dict[str, Any]:
    episodes = [episode for session in sessions for episode in session.get("episodes", [])]
    segments = [segment for episode in episodes for segment in episode.get("segments", [])]
    turns = [turn for segment in segments for turn in segment.get("turns", [])]
    return {
        "sessions": len(sessions),
        "sessions_succeeded": sum(session["status"] == "succeeded" for session in sessions),
        "sessions_partial_failed": sum(session["status"] == "partial_failed" for session in sessions),
        "sessions_failed": sum(session["status"] == "failed" for session in sessions),
        "sessions_filtered": sum(session["status"] == "filtered" for session in sessions),
        "episodes": sum(episode["status"] == "succeeded" for episode in episodes),
        "episodes_filtered": sum(episode["status"] == "filtered" for episode in episodes),
        "segments": len(segments),
        "segments_failed": sum(segment["status"] == "failed" for segment in segments),
        "turn_rows": len(turns),
        "model_calls": len(metrics),
        "prompt_tokens": sum(metric.prompt_tokens for metric in metrics),
        "completion_tokens": sum(metric.completion_tokens for metric in metrics),
        "total_tokens": sum(metric.total_tokens for metric in metrics),
        "model_elapsed_seconds": round(sum(metric.elapsed_seconds for metric in metrics), 6),
        "errors": len(errors),
    }


def _filtered_session(session: SessionInput, reason: str) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "user_id": session.user_id,
        "status": "filtered",
        "error": None,
        "filter_reason": reason,
        "turn_count": len(session.turns),
        "elapsed_seconds": 0.0,
        "episodes": [],
    }


def _failed_session(session: SessionInput, error: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "user_id": session.user_id,
        "status": "failed",
        "error": error,
        "turn_count": len(session.turns),
        "elapsed_seconds": 0.0,
        "episodes": [],
    }


def _filtered_episode(episode: Episode, reason: str) -> dict[str, Any]:
    return {
        "episode_id": episode.episode_id,
        "status": "filtered",
        "filter_reason": reason,
        "start_turn": episode.start_turn,
        "end_turn": episode.end_turn,
        "gap_before_minutes": episode.gap_before_minutes,
        "segments": [],
        "source_turns": [turn.to_dict() for turn in episode.turns],
    }


def _error_record(
    stage: str,
    session_id: str,
    exc: Exception,
    episode_id: str = "",
    segment_id: str = "",
) -> dict[str, Any]:
    return {
        "stage": stage,
        "session_id": session_id,
        "episode_id": episode_id,
        "segment_id": segment_id,
        "error_type": exc.__class__.__name__,
        "message": str(exc)[:4000] or exc.__class__.__name__,
    }


def _turn_from_dict(value: dict[str, Any]):
    from .models import Turn

    return Turn(
        int(value["turn_no"]),
        str(value["human"]),
        value.get("ai"),
        value.get("rewrite_query"),
        value.get("timestamp"),
    )


def _stage_order(stage: str) -> int:
    return {"segmentation": 0, "scenario": 1, "ai_unsupported": 2}.get(stage, 99)


def _ordinal(value: str) -> int:
    if len(value) > 1 and value[1:].isdigit():
        return int(value[1:])
    return 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _progress(callback: ProgressCallback | None, message: str) -> None:
    if callback:
        callback(message)
