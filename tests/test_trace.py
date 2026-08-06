"""The trace contract: key order, validation, byte stability, cost, and the diff.

The contract is what every scorer you write reads, so these are the tests that make
a breaking change loud. Key order is asserted literally, because it *is* the
contract.
"""

from __future__ import annotations

import json

import pytest
from conftest import a_trace

from support_agent import config, trace

KEY_ORDER = [
    "schema_version",
    "run_id",
    "timestamp",
    "fixture_id",
    "mode",
    "model",
    "params",
    "provider",
    "prompt",
    "fingerprint",
    "input",
    "steps",
    "final_output",
    "stop_reason",
    "usage",
    "cost_usd",
    "labels",
]


def test_key_order_is_the_contract() -> None:
    built = trace.TraceBuilder(
        run_id="run-refund-outside-window-01",
        fixture_id="refund-outside-window",
        mode="live",
        model="claude-sonnet-5",
        params={"max_tokens": 2048, "temperature": 1.0},
        customer_id="cust-1042",
        session_id="sess-0088",
        message="m",
        system_prompt="s",
        tool_schemas=[],
        fingerprint={
            "prompt_sha256": "a" * 64,
            "tools_sha256": "b" * 64,
            "corpus_sha256": "c" * 64,
        },
    ).build("done", "end_turn")

    assert list(built) == KEY_ORDER
    trace.validate(built)
    # A field added to the builder and not the schema, or the reverse, is the drift
    # this catches.
    schema = trace._validator().schema
    assert set(schema["required"]) == set(schema["properties"]) == set(KEY_ORDER)


def test_a_written_trace_round_trips_byte_for_byte(tmp_path) -> None:
    """Byte stability under re-serialisation. Without it, comparing a frozen trace
    against a fresh run is noise."""
    path = tmp_path / "t.jsonl"
    trace.write(a_trace(run_id="run-x-01"), path)
    trace.write(a_trace(run_id="run-x-02"), path)

    runs = trace.read(path)
    assert [run["run_id"] for run in runs] == ["run-x-01", "run-x-02"]
    assert trace.dumps(runs[0]) == trace.dumps(a_trace(run_id="run-x-01"))


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda t: {k: v for k, v in t.items() if k != "labels"}, id="no-labels"),
        pytest.param(lambda t: {k: v for k, v in t.items() if k != "params"}, id="no-params"),
        pytest.param(lambda t: dict(t, stop_reason="banana"), id="unknown-stop-reason"),
        # tool_use and pause_turn are absent from the enum on purpose: the loop
        # continues past both, so neither can ever end a run.
        pytest.param(lambda t: dict(t, stop_reason="tool_use"), id="continue-reason"),
        pytest.param(lambda t: dict(t, schema_version="2.0"), id="wrong-version"),
        pytest.param(lambda t: dict(t, extra_field=1), id="unknown-field"),
        pytest.param(
            lambda t: dict(t, steps=[{"step_id": 0, "source": "user", "message": "m"}]),
            id="user-step-without-rendered",
        ),
        pytest.param(
            lambda t: dict(
                t,
                steps=[
                    {
                        "step_id": 0,
                        "source": "system",
                        "observations": [{"source_call_id": "tc-1", "content": {}}],
                    }
                ],
            ),
            id="observation-without-is-error",
        ),
    ],
)
def test_off_contract_traces_are_rejected(mutate) -> None:
    with pytest.raises(trace.TraceValidationError):
        trace.validate(mutate(a_trace()))


def test_tool_names_and_arguments_are_unconstrained() -> None:
    """Add a parameter, rename a tool, add a fourth one — existing traces still
    validate and existing scorers still parse. The schema does not encode the tool
    surface, so changing the tools is not a schema change."""
    trace.validate(
        a_trace(
            steps=[
                {"step_id": 0, "source": "user", "message": "m", "rendered": "r"},
                {
                    "step_id": 1,
                    "source": "agent",
                    "message": "",
                    "tool_calls": [
                        {
                            "tool_call_id": "tc-1",
                            "name": "a_tool_that_does_not_exist_yet",
                            "arguments": {"customer_id": "cust-1042", "nested": {"deep": [1]}},
                        }
                    ],
                },
            ]
        )
    )


def test_cost_is_priced_per_million_tokens() -> None:
    assert config.cost_usd("claude-sonnet-5", 1_000_000, 0, 0) == 3.0
    assert config.cost_usd("claude-sonnet-5", 0, 1_000_000, 0) == 15.0
    # Cache reads bill at a tenth of the input rate.
    assert config.cost_usd("claude-sonnet-5", 0, 0, 1_000_000) == 0.3
    # An unknown model falls back rather than raising: a wrong cost is recoverable,
    # a run that dies on its last line after the money is spent is not.
    assert config.cost_usd("some-future-model", 1_000_000, 0, 0) == 3.0
    # Rounded, so the field is stable under re-serialisation.
    value = config.cost_usd("claude-sonnet-5", 1237, 91, 13)
    assert value == round(value, config.COST_PRECISION) == json.loads(json.dumps(value))


def test_run_ids_carry_a_repeat_index() -> None:
    """Without the index every repeat of a fixture shares a ``runs/<run_id>/``
    directory and deletes the side effects of the one before it."""
    assert trace.run_id_for("refund-outside-window", 3) == "run-refund-outside-window-03"
    assert len({trace.run_id_for("f", i) for i in range(1, 6)}) == 5


def test_diff_normalises_the_volatile_fields_away() -> None:
    """Two live runs of one unchanged prompt differ in all of these, every time."""
    left = a_trace()
    right = dict(
        left,
        run_id="run-refund-outside-window-07",
        timestamp="2026-08-01T09:00:00+00:00",
        mode="replay",
        usage={"input_tokens": 99, "output_tokens": 99, "cached_tokens": 99},
        cost_usd=0.5,
    )

    assert trace.diff(left, right) == []
    assert set(trace.VOLATILE_FIELDS) == {"run_id", "timestamp", "mode", "usage", "cost_usd"}


def test_diff_attributes_a_change_to_the_surface_that_caused_it() -> None:
    """``fingerprint`` is deliberately not volatile: it is the independent variable,
    and a comparison that hid a prompt change would be worse than useless."""
    left = a_trace()
    right = dict(
        left,
        prompt={"system": "A rewritten system prompt.", "tools": []},
        fingerprint={**left["fingerprint"], "prompt_sha256": "d" * 64},
        params={**left["params"], "temperature": 0.0},
        stop_reason="escalated",
    )

    lines = trace.diff(left, right)
    assert lines[0] == "~ fingerprint: prompt templates changed"
    assert lines[1] == "  (unchanged: tool definitions, corpus)"
    assert "~ stop_reason: 'end_turn' -> 'escalated'" in lines
    assert "~ params.temperature: 1.0 -> 0.0" in lines
    assert "~ prompt.system: rendered system prompt changed" in lines


def test_diff_reports_behaviour_rather_than_prose() -> None:
    """Two live runs phrase the same decision differently every time, so a text
    diff would bury the signal. Whether a changed answer is *better* is a scorer's
    question, not this function's."""
    left = a_trace()
    right = json.loads(json.dumps(left))
    right["steps"][1]["tool_calls"][0]["arguments"] = {"order_id": "B-5510"}
    right["steps"][0]["retrieved"] = [{"doc_id": "kb-refunds-01", "score": 0.9, "text": "t"}]
    right["final_output"] = "A differently worded refusal."

    lines = trace.diff(left, right)
    assert any("A-3391" in line and "B-5510" in line for line in lines)
    assert any(line.startswith("~ retrieved[turn 0]") for line in lines)
    assert any(line.startswith("~ final_output: changed") for line in lines)
    # And nothing that quotes the new wording.
    assert not any("differently worded" in line for line in lines)
