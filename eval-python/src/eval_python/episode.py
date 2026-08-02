"""Deterministic Episode splitting and Segment coverage validation."""

from __future__ import annotations

from datetime import datetime

from .models import AgentError, Episode, SegmentBoundary, Turn


def split_episodes(turns: tuple[Turn, ...], threshold_minutes: float) -> list[Episode]:
    episodes: list[Episode] = []
    current: list[Turn] = []
    gap_before: float | None = None

    for index, turn in enumerate(turns):
        previous = turns[index - 1] if index > 0 else None
        previous_time = _parse_timestamp(previous.timestamp) if previous else None
        current_time = _parse_timestamp(turn.timestamp)
        if current and previous_time is not None and current_time is not None:
            gap_minutes = (current_time - previous_time).total_seconds() / 60
            if gap_minutes > threshold_minutes:
                episodes.append(Episode(f"e{len(episodes) + 1}", tuple(current), gap_before))
                current = []
                gap_before = round(gap_minutes, 1)
        current.append(turn)

    if current:
        episodes.append(Episode(f"e{len(episodes) + 1}", tuple(current), gap_before))
    return episodes


def validate_segment_coverage(turns: tuple[Turn, ...], segments: list[SegmentBoundary]) -> None:
    if not segments:
        raise AgentError("Segment Agent returned no segments")
    expected = list(range(1, len(turns) + 1))
    actual: list[int] = []
    for index, segment in enumerate(segments, start=1):
        if segment.segment_id != f"s{index}":
            raise AgentError("Segment IDs must be consecutive")
        if segment.start_turn > segment.end_turn:
            raise AgentError(f"Invalid Segment range: {segment.start_turn}-{segment.end_turn}")
        actual.extend(range(segment.start_turn, segment.end_turn + 1))
    if actual != expected:
        raise AgentError("Segments must cover each Episode Turn exactly once")


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None

