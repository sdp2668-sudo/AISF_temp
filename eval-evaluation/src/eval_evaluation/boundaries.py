"""Boundary extraction and deterministic one-to-one matching."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BoundaryMatch:
    qwen_position: int
    baseline_position: int
    offset: int


def boundaries_from_segment_labels(turns: list[dict]) -> tuple[list[int], list[int]]:
    """Return boundary positions and ordered turn numbers from flattened rows."""
    ordered = sorted(turns, key=lambda row: int(row["turn_index"]))
    turn_numbers = [int(row["turn_index"]) for row in ordered]
    if len(turn_numbers) != len(set(turn_numbers)):
        raise ValueError("Episode contains duplicate turn_index values")
    labels = [str(row["segment_id"]) for row in ordered]
    if any(not label for label in labels):
        raise ValueError("Episode contains an empty segment_id")
    return [index for index in range(len(labels) - 1) if labels[index] != labels[index + 1]], turn_numbers


def match_boundaries(
    qwen_boundaries: list[int],
    baseline_boundaries: list[int],
    *,
    tolerance: int,
) -> tuple[list[BoundaryMatch], list[int], list[int]]:
    """Match ordered boundaries, maximizing matches then minimizing total offset."""
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    qwen = tuple(sorted(qwen_boundaries))
    baseline = tuple(sorted(baseline_boundaries))
    # Cell values are (matched count, total distance, pairs). The comparison
    # order guarantees maximum cardinality followed by the closest alignment.
    table: list[list[tuple[int, int, tuple[tuple[int, int], ...]]]] = [
        [(0, 0, ()) for _ in range(len(baseline) + 1)]
        for _ in range(len(qwen) + 1)
    ]
    for qi in range(1, len(qwen) + 1):
        for bi in range(1, len(baseline) + 1):
            candidates = [table[qi - 1][bi], table[qi][bi - 1]]
            distance = abs(qwen[qi - 1] - baseline[bi - 1])
            if distance <= tolerance:
                count, total, pairs = table[qi - 1][bi - 1]
                candidates.append((count + 1, total + distance, pairs + ((qi - 1, bi - 1),)))
            table[qi][bi] = max(candidates, key=lambda item: (item[0], -item[1], item[2]))
    _, _, pairs = table[-1][-1]
    matches = [BoundaryMatch(qwen[q], baseline[b], qwen[q] - baseline[b]) for q, b in pairs]
    used_qwen = {pair[0] for pair in pairs}
    used_baseline = {pair[1] for pair in pairs}
    return matches, [value for index, value in enumerate(qwen) if index not in used_qwen], [value for index, value in enumerate(baseline) if index not in used_baseline]


def metric_values(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    if tp == fp == fn == 0:
        return {"tp": 0, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0, "f1": 1.0}
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}
