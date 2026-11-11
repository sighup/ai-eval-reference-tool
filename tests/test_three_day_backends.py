"""The three-day course's SQLite backend and its two runners (agent.py and claude -p).

No network and no API key: the API runner is driven by a scripted model, and the
Claude Code runner's parser is fed a recorded event stream.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "three-day" / "lab"
sys.path.insert(0, str(LAB))


@pytest.fixture(autouse=True)
def sqlite_backend(monkeypatch, tmp_path):
    seed = tmp_path / "northwind.db"
    sys.path.insert(0, str(ROOT / "three-day" / "db"))
    import seed as seed_module

    seed_module.build(seed)
    monkeypatch.setenv("SUPPORT_AGENT_BACKEND", "sqlite")
    monkeypatch.setenv("SUPPORT_AGENT_DB", str(seed))
    yield


class ScriptedProvider:
    """Plays back fixed turns, the way LiveProvider would hand them to agent.py."""

    mode = "live"
    model = "scripted"
    params = {"max_tokens": 2048, "temperature": 1.0}

    def __init__(self, turns):
        self.turns = list(turns)

    def next_turn(self, system, messages, tool_schemas):
        return self.turns.pop(0)


def _turns_refund(order_id: str, amount: int):
    from support_agent.model import ModelTurn, ToolCall

    return [
        ModelTurn("", "tool_use", (ToolCall("tc-1", "lookup_order", {"order_id": order_id}),)),
        ModelTurn(
            "",
            "tool_use",
            (
                ToolCall(
                    "tc-2",
                    "issue_refund",
                    {"order_id": order_id, "amount_cents": amount, "reason": "test"},
                ),
            ),
        ),
        ModelTurn("I've refunded it.", "end_turn"),
    ]


def test_agent_py_runs_against_the_database_and_records_effects(monkeypatch, tmp_path):
    import record
    from support_agent import model, trace

    case = json.loads((ROOT / "three-day/cases/refund-in-window.json").read_text())
    monkeypatch.setattr(model, "LiveProvider", lambda **_: ScriptedProvider(_turns_refund("B-5510", 12800)))
    monkeypatch.setattr(record, "load_cases", lambda: {"refund-in-window": case})
    out = tmp_path / "t.jsonl"

    assert record.main(["--via", "api", "--case", "refund-in-window", "--repeat", "1",
                        "--out", str(out)]) == 0

    run = trace.read(out)[0]
    names = [s["name"] for s in run["prompt"]["tools"]]
    assert "find_orders" in names and "cancel_order" in names
    lookup = run["steps"][2]["observations"][0]["content"]
    assert lookup["shipments"] and "ship_to" in lookup  # the database's shape, not the JSON file's
    effects = json.loads(record.effects_path(out).read_text())
    assert effects["refunds"][0]["amount_cents"] == 12800
    assert effects["refunds"][0]["order_customer_id"] == "cust-2071"


def test_each_run_starts_from_a_fresh_database():
    from support_agent import sqlite_store, tools

    session = tools.Session("t-fresh", "cust-2071", "s")
    tools.reset_run_dir("t-fresh")
    tools.execute("issue_refund", {"order_id": "B-5510", "amount_cents": 100, "reason": "x"}, session)
    assert len(sqlite_store.effects(tools.run_dir("t-fresh"), "t-fresh")["refunds"]) == 1
    tools.reset_run_dir("t-fresh")
    assert sqlite_store.effects(tools.run_dir("t-fresh"), "t-fresh")["refunds"] == []


def test_injected_faults_fail_once_or_always():
    from support_agent import tools

    tools.reset_run_dir("t-faults")
    s = tools.Session("t-faults", "cust-8394", "s")
    assert tools.execute("lookup_order", {"order_id": "A-3509"}, s).is_error
    assert not tools.execute("lookup_order", {"order_id": "A-3509"}, s).is_error
    s2 = tools.Session("t-faults", "cust-4104", "s")
    args = {"order_id": "A-3282", "amount_cents": 3200, "reason": "x"}
    assert tools.execute("issue_refund", args, s2).is_error
    assert tools.execute("issue_refund", args, s2).is_error


def test_find_and_cancel_are_scoped_but_lookup_is_not():
    from support_agent import tools

    tools.reset_run_dir("t-scope")
    s = tools.Session("t-scope", "cust-1042", "s")
    found = tools.execute("find_orders", {}, s).content["orders"]
    assert "B-5510" not in {o["order_id"] for o in found}
    assert tools.execute("cancel_order", {"order_id": "B-5522", "reason": "x"}, s).is_error
    # The planted flaw the course is about: lookup_order does not check the owner.
    assert not tools.execute("lookup_order", {"order_id": "B-5510"}, s).is_error


def test_claude_stream_becomes_a_valid_trace():
    import record
    from support_agent import agent, prompts, tools, trace

    case = json.loads((ROOT / "three-day/cases/refund-in-window.json").read_text())
    fixture = agent.Fixture.from_dict(case)
    schemas = tools.tool_schemas()
    events = [
        {"type": "system", "subtype": "init", "model": "claude-haiku-5-5",
         "claude_code_version": "x"},
        {"type": "assistant", "message": {"id": "m1", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "mcp__northwind__lookup_order",
             "input": {"order_id": "B-5510"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "toolu_1",
             "content": [{"type": "text", "text": "{\"order_id\": \"B-5510\"}"}]}]}},
        {"type": "assistant", "message": {"id": "m2", "content": [
            {"type": "text", "text": "Done."}]}},
        {"type": "result", "subtype": "success", "stop_reason": "end_turn",
         "total_cost_usd": 0.001,
         "usage": {"input_tokens": 5, "output_tokens": 7, "cache_read_input_tokens": 11}},
    ]
    system = prompts.render_system(fixture.customer_id, fixture.session_id, "2026-07-28")
    built = record.to_trace(events, fixture, "run-x-01", "2026-07-28", system, schemas, [],
                            "rendered", None)
    trace.validate(built)
    assert built["steps"][1]["tool_calls"][0]["name"] == "lookup_order"  # prefix stripped
    assert built["steps"][2]["observations"][0]["content"] == {"order_id": "B-5510"}
    assert built["final_output"] == "Done." and built["stop_reason"] == "end_turn"
    assert built["params"]["runner"] == "claude-code"
