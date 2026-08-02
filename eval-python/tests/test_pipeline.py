from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from eval_python.config import load_config
from eval_python.models import SessionInput, Turn
from eval_python.pipeline import run_pipeline
from eval_python.taxonomy import load_taxonomy

from .helpers import RoutingClient


ROOT = Path(__file__).resolve().parents[1]


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config" / "qwen.example.yaml")
        self.taxonomy = load_taxonomy(self.config.taxonomy_path)
        self.sessions = [SessionInput(
            session_id="session-1",
            user_id="user-1",
            turns=(
                Turn(1, "你好", "你好", "你好通通", "2026-07-27T10:00:00+08:00"),
                Turn(2, "今天天气怎样", "晴", None, "2026-07-27T10:01:00+08:00"),
            ),
            declared_turn_count=2,
        )]

    def test_disabled_optional_stages_are_unambiguous_and_make_no_refusal_call(self):
        config = replace(
            self.config,
            features=replace(
                self.config.features,
                enable_subscene=False,
                enable_ai_unsupported=False,
            ),
            pipeline=replace(
                self.config.pipeline,
                session_concurrency=1,
                segment_concurrency=1,
            ),
        )
        clients: list[RoutingClient] = []

        def factory():
            client = RoutingClient()
            clients.append(client)
            return client

        result = run_pipeline(
            self.sessions,
            config,
            self.taxonomy,
            input_file="sessions.json",
            client_factory=factory,
        )

        segment = result["sessions"][0]["episodes"][0]["segments"][0]
        self.assertEqual([call for client in clients for call in client.calls], ["segmentation", "scenario"])
        self.assertEqual([turn["turn_no"] for turn in segment["turns"]], [1, 2])
        self.assertEqual(segment["business"], "语音对话")
        self.assertIsNone(segment["sub_function"])
        self.assertIsNone(segment["ai_unsupported"])
        self.assertIsNone(segment["judgment_reason"])
        self.assertIsNone(segment["refusal_findings"])
        self.assertEqual(result["summary"]["turn_rows"], 2)
        self.assertEqual(result["summary"]["model_calls"], 2)
        self.assertEqual(result["summary"]["errors"], 0)

    def test_enabled_refusal_zero_hit_is_distinct_from_disabled(self):
        config = replace(
            self.config,
            pipeline=replace(
                self.config.pipeline,
                session_concurrency=1,
                segment_concurrency=1,
            ),
        )
        clients: list[RoutingClient] = []

        def factory():
            client = RoutingClient()
            clients.append(client)
            return client

        result = run_pipeline(
            self.sessions,
            config,
            self.taxonomy,
            input_file="sessions.json",
            client_factory=factory,
        )

        segment = result["sessions"][0]["episodes"][0]["segments"][0]
        self.assertEqual(segment["sub_function"], "闲聊")
        self.assertEqual(segment["ai_unsupported"], "否")
        self.assertEqual(segment["judgment_reason"], "")
        self.assertEqual(segment["refusal_findings"], [])
        self.assertEqual(result["summary"]["model_calls"], 3)
        self.assertIn("ai_unsupported", [call for client in clients for call in client.calls])


if __name__ == "__main__":
    unittest.main()
