from __future__ import annotations

import unittest

from eval_evaluation.boundaries import boundaries_from_segment_labels, match_boundaries
from eval_evaluation.metrics import evaluate_episode


def episode(boundaries: list[int], turns: list[int] | None = None) -> dict:
    turns = turns or list(range(1, 9))
    labels = []
    segment = 1
    for position, turn in enumerate(turns):
        labels.append(str(segment))
        if position in boundaries:
            segment += 1
    rows = [{"turn_index": turn, "segment_id": label, "human": "", "ai": ""} for turn, label in zip(turns, labels)]
    found, turn_numbers = boundaries_from_segment_labels(rows)
    return {"session_id": "s", "episode_id": "e", "start_turn": turns[0], "end_turn": turns[-1], "turn_numbers": turn_numbers, "turns": rows, "boundaries": found, "segment_count": len(found) + 1}


class BoundaryMetricTest(unittest.TestCase):
    def test_exact_and_loose_metrics_are_separate(self):
        result = evaluate_episode(episode([3, 6]), episode([2, 6]), 1)
        self.assertEqual((result["strict"]["tp"], result["strict"]["fp"], result["strict"]["fn"]), (1, 1, 1))
        self.assertEqual((result["loose"]["tp"], result["loose"]["fp"], result["loose"]["fn"]), (2, 0, 0))
        self.assertEqual(result["classification"], "loose_only_match")

    def test_one_reference_boundary_cannot_match_two_qwen_boundaries(self):
        matches, fp, fn = match_boundaries([2, 3], [2], tolerance=1)
        self.assertEqual(len(matches), 1)
        self.assertEqual(fp, [3])
        self.assertEqual(fn, [])

    def test_non_contiguous_turn_numbers_use_effective_positions(self):
        qwen = episode([1], [10, 20, 50, 80])
        baseline = episode([2], [10, 20, 50, 80])
        result = evaluate_episode(qwen, baseline, 1)
        self.assertEqual(result["loose"]["f1"], 1.0)

    def test_single_segment_episode_is_perfect(self):
        result = evaluate_episode(episode([]), episode([]), 1)
        self.assertEqual(result["strict"]["f1"], 1.0)
        self.assertEqual(result["loose"]["f1"], 1.0)
