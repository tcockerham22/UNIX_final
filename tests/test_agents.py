"""Tests for Ada's delegated sub-agents."""

from __future__ import annotations

import queue
import unittest
from unittest.mock import patch

from ada import agents, events, tools as tool_mod
from ada.config import Config


def _response(content: str = "", calls: list | None = None) -> dict:
    return {"message": {"content": content, "tool_calls": calls or []}}


def _call(name: str, arguments: dict | None = None) -> dict:
    return {"function": {"name": name, "arguments": arguments or {}}}


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.bus = events.bus
        self.subscriber = self.bus.subscribe(after=self.bus._seq)
        self.seen: list[dict] = []

    def tearDown(self):
        self.bus.unsubscribe(self.subscriber)

    def collect(self) -> list[dict]:
        while True:
            try:
                self.seen.append(self.subscriber.get_nowait())
            except queue.Empty:
                break
        return self.seen

    def test_empty_task_is_rejected(self):
        self.assertTrue(agents.run_subagent("   ", self.config, None).startswith("ERROR"))

    def test_disabled_agents_are_rejected(self):
        self.config.agents_enabled = False
        result = agents.run_subagent("Do something", self.config, None)
        self.assertIn("disabled", result)

    def test_returns_final_text_and_uses_light_model_by_default(self):
        with patch.object(agents.ollama, "chat", return_value=_response("The answer")) as chat:
            result = agents.run_subagent("Find the answer", self.config, None)
        self.assertEqual(result, "The answer")
        kwargs = chat.call_args.kwargs
        self.assertEqual(kwargs["model"], self.config.light_model)
        system = kwargs["messages"][0]["content"]
        self.assertIn("Find the answer", system)
        self.assertIn("You cannot delegate further", system)
        self.assertEqual(kwargs["messages"][1], {"role": "user", "content": "Find the answer"})

    def test_model_tier_override(self):
        with patch.object(agents.ollama, "chat", return_value=_response("ok")) as chat:
            agents.run_subagent("Think hard", self.config, None, model_tier="deep")
        self.assertEqual(chat.call_args.kwargs["model"], self.config.deep_model)

    def test_tool_loop_feeds_results_back_and_hides_internal_events(self):
        responses = [
            _response(calls=[_call("web_search", {"query": "x"})]),
            _response("Final result"),
        ]

        def fake_run_tool(name, args, memory, config):
            events.emit("action", kind="internal")
            return "tool output"

        with patch.object(agents.ollama, "chat", side_effect=responses) as chat, \
             patch.object(agents.tool_mod, "run_tool", side_effect=fake_run_tool):
            result = agents.run_subagent("Research x", self.config, None)

        self.assertEqual(result, "Final result")
        self.assertEqual(chat.call_count, 2)
        messages = chat.call_args_list[0].kwargs["messages"]
        self.assertEqual(messages[2]["tool_calls"][0]["function"]["name"], "web_search")
        self.assertEqual(messages[3]["role"], "tool")
        self.assertEqual(messages[3]["content"], "tool output")

        emitted = self.collect()
        agent_events = [e for e in emitted if e["type"] == "agent"]
        self.assertEqual(len(agent_events), 2)
        self.assertEqual(
            {e["data"]["status"] for e in agent_events}, {"start", "done"}
        )
        self.assertNotIn("action", [e["type"] for e in emitted])

    def test_agents_cannot_spawn_agents(self):
        requested = ["spawn_agent", "spawn_agents", "web_search", "run_command"]
        with patch.object(agents.ollama, "chat", return_value=_response("ok")) as chat:
            agents.run_subagent("Task", self.config, None, tools=requested)
        names = [t["function"]["name"] for t in chat.call_args.kwargs["tools"]]
        self.assertEqual(names, ["web_search", "run_command"])

    def test_run_agents_returns_labelled_results_in_order(self):
        with patch.object(agents, "run_subagent", side_effect=["first", "second"]) as run:
            result = agents.run_agents(["task one", "task two"], self.config, None)
        self.assertEqual(run.call_count, 2)
        self.assertIn("Agent 1 — task one\nfirst", result)
        self.assertIn("Agent 2 — task two\nsecond", result)
        self.assertLess(result.index("Agent 1"), result.index("Agent 2"))

    def test_run_subagent_stops_at_round_limit(self):
        self.config.agent_max_rounds = 2
        responses = [
            _response(calls=[_call("web_search", {"query": "x"})]),
            _response(calls=[_call("web_search", {"query": "y"})]),
        ]
        with patch.object(agents.ollama, "chat", side_effect=responses) as chat, \
             patch.object(agents.tool_mod, "run_tool", return_value="out"):
            result = agents.run_subagent("Loop forever", self.config, None)
        self.assertEqual(chat.call_count, 2)
        self.assertIn("step limit", result)

    def test_tool_dispatch(self):
        with patch.object(tool_mod, "ensure_reminders"), \
             patch.object(agents, "run_subagent", return_value="dispatched") as run:
            result = tool_mod.run_tool("spawn_agent", {"task": "hello"}, None, self.config)
        self.assertEqual(result, "dispatched")
        self.assertEqual(run.call_args.args[0], "hello")

        with patch.object(tool_mod, "ensure_reminders"), \
             patch.object(agents, "run_agents", return_value="many") as run_many:
            result = tool_mod.run_tool(
                "spawn_agents", {"tasks": ["one", "two"]}, None, self.config
            )
        self.assertEqual(result, "many")
        self.assertEqual(run_many.call_args.args[0], ["one", "two"])


if __name__ == "__main__":
    unittest.main()
