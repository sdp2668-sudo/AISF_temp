from __future__ import annotations

import unittest
from pathlib import Path

from eval_python.models import Turn
from eval_python.prompts import REASON_NO_CAPABILITY
from eval_python.refusal_agent import run_refusal_agent
from eval_python.scenario_agent import run_scenario_agent
from eval_python.segment_agent import run_segment_agent
from eval_python.taxonomy import load_taxonomy

from .helpers import ScriptedClient, tool_message


ROOT = Path(__file__).resolve().parents[1]


def turns(count=4):
    return tuple(
        Turn(index, f"用户-{index}", f"助手-{index}", None, f"2026-07-27T10:0{index}:00+08:00")
        for index in range(1, count + 1)
    )


class AgentsTest(unittest.TestCase):
    def test_segment_agent_supports_undo_and_preserves_full_rules(self):
        client = ScriptedClient([
            tool_message("add_segment", {"endTurn": 2, "intentSummary": "过早", "noiseTurns": []}, "c1"),
            tool_message("undo_last_segment", {}, "c2"),
            tool_message("add_segment", {"endTurn": 3, "intentSummary": "合并意图", "noiseTurns": [2]}, "c3"),
            tool_message("add_segment", {"endTurn": 4, "intentSummary": "新意图", "noiseTurns": []}, "c4"),
        ])
        result = run_segment_agent(
            client,
            turns(),
            session_id="session-1",
            episode_id="e1",
            window_size=2,
            max_rounds=10,
        )
        self.assertEqual(
            [(item.segment_id, item.start_turn, item.end_turn) for item in result.value],
            [("s1", 1, 3), ("s2", 4, 4)],
        )
        self.assertEqual(result.value[0].noise_turns, (2,))
        prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("连续三次及以上", prompt)
        self.assertIn("同为通通学习下的不同学科", prompt)
        visible = client.calls[0]["messages"][1]["content"]
        self.assertIn("用户-1", visible)
        self.assertIn("用户-2", visible)
        self.assertNotIn("助手-1", visible)

    def test_scenario_full_pair_retries_invalid_sub_function(self):
        taxonomy = load_taxonomy(ROOT / "config" / "scenario-taxonomy.json")
        client = ScriptedClient([
            tool_message("submit_tag", {"业务": "音乐", "子功能": "不存在"}, "c1"),
            tool_message("submit_tag", {"业务": "音乐", "子功能": "控制"}, "c2"),
        ])
        result = run_scenario_agent(
            client,
            taxonomy,
            "打开酷狗",
            session_id="session-1",
            episode_id="e1",
            segment_id="s1",
            enable_subscene=True,
            max_rounds=5,
        )
        self.assertEqual(result.value.business, "音乐")
        self.assertEqual(result.value.sub_function, "控制")
        self.assertTrue(result.value.is_control)
        self.assertEqual(len(result.metrics), 2)
        prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("业务层看内容载体与诉求类别", prompt)
        self.assertIn("对象类型举例", prompt)

    def test_disabled_subscene_uses_business_only_tool(self):
        taxonomy = load_taxonomy(ROOT / "config" / "scenario-taxonomy.json")
        client = ScriptedClient([tool_message("submit_business", {"业务": "语音对话"})])
        result = run_scenario_agent(
            client,
            taxonomy,
            "你好通通",
            session_id="session-1",
            episode_id="e1",
            segment_id="s1",
            enable_subscene=False,
            max_rounds=3,
        )
        properties = client.calls[0]["tools"][0]["function"]["parameters"]["properties"]
        self.assertEqual(set(properties), {"业务"})
        self.assertEqual(result.value.business, "语音对话")
        self.assertIsNone(result.value.sub_function)
        self.assertIsNone(result.value.is_control)

    def test_refusal_zero_findings_and_hit_preserve_distinct_results(self):
        no_hit_client = ScriptedClient([tool_message("submit_findings", {"findings": []})])
        no_hit = run_refusal_agent(
            no_hit_client,
            turns(1),
            session_id="session-1",
            episode_id="e1",
            segment_id="s1",
            max_rounds=3,
        )
        self.assertEqual(no_hit.value.ai_unsupported, "否")
        self.assertEqual(no_hit.value.findings, ())

        hit_client = ScriptedClient([tool_message("submit_findings", {
            "findings": [{"轮次": 1, "判定原因": REASON_NO_CAPABILITY}],
        })])
        hit = run_refusal_agent(
            hit_client,
            (Turn(1, "打开应用", "抱歉，我无法打开", None, None),),
            session_id="session-1",
            episode_id="e1",
            segment_id="s1",
            max_rounds=3,
        )
        self.assertEqual(hit.value.ai_unsupported, "是")
        self.assertEqual(hit.value.findings[0].turn_no, 1)
        self.assertIn("[提示:疑似硬失败]", hit_client.calls[0]["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()

