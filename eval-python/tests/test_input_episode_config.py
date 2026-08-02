from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eval_python.config import load_config
from eval_python.episode import split_episodes
from eval_python.input import load_sessions
from eval_python.models import InputError, Turn
from eval_python.taxonomy import load_taxonomy


ROOT = Path(__file__).resolve().parents[1]


class InputEpisodeConfigTest(unittest.TestCase):
    def test_example_config_defaults_keep_all_data_and_match_qwen_example(self):
        config = load_config(ROOT / "config" / "qwen.example.yaml")
        self.assertEqual(config.model.endpoint, "http://9.15.87.94:1065/v1/chat/completions")
        self.assertEqual(config.model.name, "Qwen3-32B")
        self.assertIsNone(config.model.api_key_env)
        self.assertFalse(config.model.enable_thinking)
        self.assertFalse(config.model.verify_tls)
        self.assertEqual(config.filters.excluded_user_ids, ())
        self.assertIsNone(config.filters.max_episode_turns)
        taxonomy = load_taxonomy(config.taxonomy_path)
        self.assertEqual(len(taxonomy.entries), 48)
        self.assertIn("语音对话", taxonomy.businesses)

    def test_input_sorts_turns_preserves_rewrite_and_normalizes_empty_ai(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.json"
            path.write_text(json.dumps([{
                "session_id": "s1",
                "user_id": "u1",
                "turn_count": 2,
                "turns": [
                    {"turn_no": 2, "human": "第二轮", "ai": "", "timestamp": "2026-07-27T10:30:00+08:00"},
                    {
                        "turn_no": 1,
                        "human": "第一轮",
                        "ai": "回答",
                        "rewrite_query": "改写",
                        "timestamp": "2026-07-27T10:00:00+08:00",
                    },
                ],
            }], ensure_ascii=False), encoding="utf-8")
            session = load_sessions(path)[0]
        self.assertEqual([turn.turn_no for turn in session.turns], [1, 2])
        self.assertEqual(session.turns[0].rewrite_query, "改写")
        self.assertIsNone(session.turns[1].ai)

    def test_input_rejects_duplicate_turn_number(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.json"
            path.write_text(json.dumps([{
                "session_id": "s1",
                "user_id": "u1",
                "turns": [
                    {"turn_no": 1, "human": "a", "ai": None, "timestamp": ""},
                    {"turn_no": 1, "human": "b", "ai": None, "timestamp": ""},
                ],
            }]), encoding="utf-8")
            with self.assertRaisesRegex(InputError, "duplicate turn_no"):
                load_sessions(path)

    def test_episode_split_is_strictly_greater_than_30_minutes(self):
        turns = (
            Turn(1, "a", None, None, "2026-07-27T10:00:00+08:00"),
            Turn(2, "b", None, None, "2026-07-27T10:30:00+08:00"),
            Turn(3, "c", None, None, "2026-07-27T11:00:01+08:00"),
            Turn(4, "d", None, None, "not-a-time"),
        )
        episodes = split_episodes(turns, 30)
        self.assertEqual(
            [[turn.turn_no for turn in episode.turns] for episode in episodes],
            [[1, 2], [3, 4]],
        )
        self.assertEqual(episodes[1].gap_before_minutes, 30.0)


if __name__ == "__main__":
    unittest.main()
