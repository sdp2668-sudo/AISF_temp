from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from eval_python.config import load_config
from eval_python.models import ModelError
from eval_python.qwen_client import QwenClient


ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.body = body

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.trust_env = True

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class QwenClientTest(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config" / "qwen.example.yaml").model

    def test_request_matches_supplied_qwen_form_without_authorization(self):
        response = FakeResponse(200, {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
        })
        session = FakeSession([response])
        result = QwenClient(self.config, session=session).chat([{"role": "user", "content": "test"}])
        url, request = session.calls[0]
        self.assertEqual(url, "http://9.15.87.94:1065/v1/chat/completions")
        self.assertEqual(request["json"]["model"], "Qwen3-32B")
        self.assertEqual(request["json"]["temperature"], 0)
        self.assertEqual(request["json"]["chat_template_kwargs"], {"enable_thinking": False})
        self.assertNotIn("tools", request["json"])
        self.assertNotIn("Authorization", request["headers"])
        self.assertFalse(request["verify"])
        self.assertFalse(session.trust_env)
        self.assertEqual(result.usage["total_tokens"], 4)

    def test_tools_are_added_and_retryable_status_uses_backoff(self):
        session = FakeSession([
            FakeResponse(500, {"error": {"message": "busy"}}),
            FakeResponse(200, {"choices": [{"message": {"role": "assistant", "tool_calls": []}}]}),
        ])
        sleeps = []
        client = QwenClient(
            replace(self.config, retry_backoff_seconds=0.25),
            session=session,
            sleep=sleeps.append,
        )
        result = client.chat(
            [{"role": "user", "content": "test"}],
            [{"type": "function", "function": {"name": "submit", "parameters": {}}}],
        )
        self.assertEqual(result.attempts, 2)
        self.assertEqual(sleeps, [0.25])
        self.assertEqual(session.calls[0][1]["json"]["tool_choice"], "auto")

    def test_invalid_success_envelope_is_an_error(self):
        client = QwenClient(self.config, session=FakeSession([FakeResponse(200, {"choices": []})]))
        with self.assertRaisesRegex(ModelError, r"choices\[0\]"):
            client.chat([{"role": "user", "content": "test"}])


if __name__ == "__main__":
    unittest.main()

