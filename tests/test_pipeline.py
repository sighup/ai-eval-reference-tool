"""End-to-end runs of the whole pipeline.

Everything else in this directory tests one deterministic piece. These run the
real thing: retrieval, prompt rendering, the loop, tool dispatch, side effects, the
trace writer, and the CLI.

1. **The golden trace.** Replaying a pinned recording reproduces a committed trace.
   This is the schema-stability check that does not depend on anyone remembering to
   look — if a change to the loop, the tool bodies, the writer or the schema alters
   the shape of a run, it goes red.
2. **The starter recordings.** Every trace under ``traces/starter/`` satisfies the
   current contract and replays clean, so a tool or schema change cannot silently
   strand the recordings learners start from.
3. **The CLI loop.** ``run`` then ``diff``, which is the sequence the course is
   built around.

What is normalised out of the recording comparisons, and why: the volatile fields,
because a replay has a different ``run_id``, ``mode``, clock reading and usage
attribution than the live run it came from; ``prompt`` and ``fingerprint``, which
are the surfaces this agent exists to have edited; and each user step's
``rendered`` content, which embeds ``prompts/context.md``. Rewriting either
template is the exercise; it must not turn the test suite red. Whether a prompt
changed is what ``support-agent diff`` reports, and that is where it belongs.

The corpus is deliberately *not* exempt: ``retrieved`` stays in the comparison, so
editing a document that a pinned recording retrieved goes red here. That is the
correct outcome — the recording quotes policy text that no longer exists — and the
fix is to re-record, not to loosen the comparison.

**Re-freezing.** When a change to the trace shape is deliberate, regenerate the
expected file rather than editing it by hand::

    uv run python -c "
    from pathlib import Path
    from support_agent import agent, replay, trace
    source = Path('tests/data/golden-source.jsonl')
    fixture = agent.Fixture.from_file(Path('fixtures/starter/005.json'))
    provider = replay.ReplayProvider.from_file(source, fixture_id=fixture.fixture_id)
    Path('tests/data/golden-replay.jsonl').write_text(
        trace.dumps(agent.run(fixture, provider, run_id='golden-replay')) + '\\n')
    "

Then read the diff before committing it. A re-freeze nobody looked at is the same as
not having the check.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import ScriptedProvider

from support_agent import agent, cli, config, model, prompts, replay, tools, trace

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "starter"
STARTER_TRACES = ROOT / "traces" / "starter"
GOLDEN_SOURCE = ROOT / "tests" / "data" / "golden-source.jsonl"
GOLDEN_EXPECTED = ROOT / "tests" / "data" / "golden-replay.jsonl"
FLAT_SUPERSET = ROOT / "tests" / "data" / "flat-superset-fixture.json"

#: Dropped before comparing a fresh replay against a committed recording. See the
#: module docstring.
NORMALISED = (*trace.VOLATILE_FIELDS, "prompt", "fingerprint")
HARNESS_LIFECYCLES = {
    "judge_dev",
    "calibration_holdout",
    "drift_regression",
    "regression",
}


def normalise(run: dict) -> dict:
    slim = {k: v for k, v in run.items() if k not in NORMALISED}
    # ``rendered`` embeds prompts/context.md, one of the editable surfaces.
    # ``retrieved`` stays, so a corpus edit remains visible.
    slim["steps"] = [{k: v for k, v in step.items() if k != "rendered"} for step in slim["steps"]]
    return slim


def validate_harness_metadata(payload: dict) -> None:
    """The learner-facing superset contract; the reference tool ignores it."""
    lifecycle = payload.get("metadata", {}).get("lifecycle")
    if lifecycle not in HARNESS_LIFECYCLES:
        raise ValueError(f"invalid fixture lifecycle: {lifecycle!r}")


def test_replaying_a_pinned_recording_reproduces_the_committed_trace() -> None:
    fixture = agent.Fixture.from_file(FIXTURES / "005.json")

    def replayed() -> dict:
        provider = replay.ReplayProvider.from_file(GOLDEN_SOURCE, fixture_id=fixture.fixture_id)
        return agent.run(fixture, provider, run_id="golden-replay")

    result = replayed()
    (expected,) = trace.read(GOLDEN_EXPECTED)

    trace.validate(result)
    assert json.dumps(normalise(result), indent=2) == json.dumps(normalise(expected), indent=2)

    # Retrieval, rendering and tool dispatch all re-run on a replay, so this is a
    # determinism check on the whole pipeline below the model.
    assert trace.dumps(normalise(replayed())) == trace.dumps(normalise(result))

    # This recording was pinned because it dispatches tools: replaying it also
    # proves side effects are reproducible, which is what a scorer that reads
    # runs/<run_id>/refund_ledger.jsonl depends on.
    called = [c["name"] for s in result["steps"] for c in s.get("tool_calls", [])]
    assert called == ["lookup_order", "issue_refund"]
    (ledger_entry,) = tools.read_ledger("golden-replay")
    assert ledger_entry["run_id"] == "golden-replay"

    # Recordings ship unlabelled. A labelled trace is an answer key, and hand
    # labelling is the exercise.
    (source,) = trace.read(GOLDEN_SOURCE)
    assert source["mode"] == "live" and source["labels"] == {}


@pytest.mark.parametrize("path", sorted(STARTER_TRACES.glob("*.jsonl")), ids=lambda p: p.stem)
def test_every_starter_recording_is_on_contract_and_replays_clean(path: Path) -> None:
    """The starter recordings are the first thing a learner replays, and the
    easiest artefact to forget when a tool or the schema changes. Each run in each
    file must satisfy the current contract, and replaying it through the current
    pipeline must reproduce it.

    When a deliberate change turns this red — a fixed tool, an evolved schema —
    replaying the stale recording to watch the new failure is still worth doing
    first (see the README's Replay section: that is how you prove a fix blocks the
    recorded behaviour). This test is what remembers the recording is stale
    afterwards: once the change is in, re-record the starter pack live and commit
    the new recordings alongside it.
    """
    recordings = trace.read(path)
    assert recordings, f"{path} holds no runs"

    for recording in recordings:
        trace.validate(recording)
        # Shipped live-recorded and unlabelled: labelling is the exercise.
        assert recording["mode"] == "live" and recording["labels"] == {}
        assert recording["fixture_id"] == path.stem

        fixture = agent.Fixture.from_dict(
            dict(recording["input"], fixture_id=recording["fixture_id"]), source=str(path)
        )
        # The recording's own run_id, so payloads that quote it — the escalation
        # queue path — reproduce exactly.
        result = agent.run(fixture, replay.ReplayProvider(recording), run_id=recording["run_id"])

        trace.validate(result)
        assert json.dumps(normalise(result), indent=2) == json.dumps(
            normalise(recording), indent=2
        ), f"replay of {path.name} run {recording['run_id']} diverged; re-record it"


def test_a_full_loop_records_everything_that_went_in_and_came_out() -> None:
    """One run driven by a scripted provider, so the requests the loop assembled can
    be inspected — the part a recording cannot express, and the part every
    conclusion a scorer draws ultimately rests on."""
    fixture = agent.Fixture.from_file(FIXTURES / "001.json")
    provider = ScriptedProvider(
        [
            model.ModelTurn(
                text="Let me look that up.",
                stop_reason="tool_use",
                tool_calls=(
                    model.ToolCall("tc-1", "lookup_order", {"order_id": "A-3391"}, "toolu_x"),
                ),
                usage=model.Usage(1000, 40, 0),
            ),
            model.ModelTurn(
                text="That order is outside the 30-day window.",
                stop_reason="end_turn",
                usage=model.Usage(1400, 60, 0),
            ),
        ]
    )

    result = agent.run(fixture, provider, run_id="pipeline-01", as_of="2026-07-28")
    trace.validate(result)

    assert [(s["step_id"], s["source"]) for s in result["steps"]] == [
        (0, "user"),
        (1, "agent"),
        (2, "system"),
        (3, "agent"),
    ]
    assert result["stop_reason"] == "end_turn"
    assert result["final_output"] == "That order is outside the 30-day window."
    assert result["usage"] == {"input_tokens": 2400, "output_tokens": 100, "cached_tokens": 0}
    assert result["cost_usd"] == config.cost_usd("claude-sonnet-5", 2400, 100, 0)

    # The user step is everything that went in, and ``rendered`` is what the model
    # was actually sent — which is what makes a templating failure visible to a
    # scorer holding nothing but the trace.
    user_step = result["steps"][0]
    assert user_step["message"] == fixture.message
    assert user_step["rendered"] == provider.requests[0][0]["content"]
    assert all(hit["doc_id"] in user_step["rendered"] for hit in user_step["retrieved"])
    assert result["prompt"]["tools"] == tools.TOOL_SCHEMAS
    # Template-agnostic: the recorded system prompt is exactly what render_system
    # produced for the as_of the caller passed, whatever system.md happens to say.
    assert result["prompt"]["system"] == prompts.render_system(
        fixture.customer_id, fixture.session_id, "2026-07-28"
    )

    # The assistant turn is rebuilt from the ModelTurn for the next request, using
    # the provider's own tool_use id — the API rejects a tool_result that references
    # anything else.
    assistant, results = provider.requests[1][1], provider.requests[1][2]
    assert assistant["content"][1]["id"] == "toolu_x"
    assert results["content"][0]["tool_use_id"] == "toolu_x"
    assert json.loads(results["content"][0]["content"])["order_id"] == "A-3391"

    observation = result["steps"][2]["observations"][0]
    assert observation["source_call_id"] == "tc-1" and observation["is_error"] is False


def test_a_terminal_tool_and_the_step_cap_both_end_a_run() -> None:
    """The two ways the loop stops a run itself, rather than being told to."""
    fixture = agent.Fixture.from_file(FIXTURES / "004.json")

    escalating = ScriptedProvider(
        [
            model.ModelTurn(
                text="Passing you to a specialist.",
                stop_reason="tool_use",
                tool_calls=(
                    model.ToolCall(
                        "tc-1",
                        "escalate_to_human",
                        {"reason": "warranty", "summary": "seam split", "priority": "high"},
                        "toolu_y",
                    ),
                ),
            ),
            model.ModelTurn(text="never requested", stop_reason="end_turn"),
        ]
    )
    escalated = agent.run(fixture, escalating, run_id="pipeline-02")
    trace.validate(escalated)
    assert escalated["stop_reason"] == "escalated"
    assert len(escalating.turns) == 1, "the run continued past the terminal tool"
    (queued,) = tools.read_ledger("pipeline-02", tools.ESCALATION_QUEUE)
    assert queued["priority"] == "high"

    looping = ScriptedProvider(
        [
            model.ModelTurn(
                text=f"turn {i}",
                stop_reason="tool_use",
                tool_calls=(model.ToolCall(f"tc-{i}", "lookup_order", {"order_id": "C-7744"}),),
            )
            for i in range(1, 6)
        ]
    )
    capped = agent.run(fixture, looping, run_id="pipeline-03", max_steps=3)
    # The trace is still written: a run that spent every turn getting nowhere is
    # evidence, and throwing it away would hide it.
    trace.validate(capped)
    assert capped["stop_reason"] == "max_steps"
    assert capped["final_output"] == "turn 3"


def test_the_cli_runs_a_fixture_then_compares_two_sets_of_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The loop the course is about, end to end: run, run again, diff."""
    before, after = tmp_path / "before.jsonl", tmp_path / "after.jsonl"
    common = ["run", "--fixture", str(FIXTURES / "005.json"), "--replay", str(GOLDEN_SOURCE)]

    assert cli.main([*common, "--repeat", "2", "--trace-out", str(before)]) == 0
    printed = capsys.readouterr().out
    assert "total cost $" in printed

    runs = trace.read(before)
    # Distinct run ids, or the repeats share a runs/<run_id>/ directory and each
    # deletes the side effects of the one before it.
    assert [r["run_id"] for r in runs] == [
        "run-refund-in-window-01",
        "run-refund-in-window-02",
    ]

    assert cli.main(["validate", str(before)]) == 0
    assert "2/2 run(s) valid" in capsys.readouterr().out

    assert cli.main([*common, "--trace-out", str(after)]) == 0
    capsys.readouterr()

    assert cli.main(["diff", str(before), str(after)]) == 0
    printed = capsys.readouterr().out
    # Same recording, same prompt: nothing behavioural moved, and the volatile
    # fields are named rather than reported as differences.
    assert "no behavioural difference" in printed
    for field in trace.VOLATILE_FIELDS:
        assert field in printed


def test_the_cli_reports_a_user_error_in_one_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing key or a typo in a path is not a bug in the tool, and a traceback
    would suggest otherwise. With no ``--replay`` and no key, the default path is
    live — which is the assertion."""
    assert cli.main(["run", "--fixture", str(FIXTURES / "001.json")]) == 1
    printed = capsys.readouterr().out
    assert "live" in printed and "MissingCredential" in printed and "Traceback" not in printed

    assert cli.main(["run", "--fixture", str(tmp_path / "nope.json")]) == 1
    assert "FileNotFoundError" in capsys.readouterr().out


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")), ids=lambda p: p.stem)
def test_every_shipped_fixture_loads(path: Path) -> None:
    loaded = agent.Fixture.from_file(path)
    assert loaded.fixture_id and loaded.customer_id and loaded.session_id and loaded.message


def test_flat_superset_fixture_loads_and_runs_like_the_minimal_fixture() -> None:
    minimal_path = FIXTURES / "001.json"
    superset_payload = json.loads(FLAT_SUPERSET.read_text(encoding="utf-8"))

    minimal = agent.Fixture.from_file(minimal_path)
    superset = agent.Fixture.from_file(FLAT_SUPERSET)
    validate_harness_metadata(superset_payload)
    assert superset == minimal

    minimal_run = agent.run(
        minimal,
        ScriptedProvider([model.ModelTurn(text="same answer", stop_reason="end_turn")]),
        run_id="minimal-fixture",
    )
    superset_run = agent.run(
        superset,
        ScriptedProvider([model.ModelTurn(text="same answer", stop_reason="end_turn")]),
        run_id="superset-fixture",
    )
    assert normalise(superset_run) == normalise(minimal_run)


def test_missing_required_generator_input_is_rejected(tmp_path: Path) -> None:
    payload = json.loads((FIXTURES / "001.json").read_text(encoding="utf-8"))
    del payload["message"]
    path = tmp_path / "missing-message.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(agent.FixtureError, match="missing message"):
        agent.Fixture.from_file(path)


def test_invalid_lifecycle_is_a_harness_error_not_a_reference_tool_input_error(
    tmp_path: Path,
) -> None:
    payload = json.loads((FIXTURES / "001.json").read_text(encoding="utf-8"))
    payload["metadata"] = {"cites": ["F1"], "lifecycle": "sometimes_holdout"}
    path = tmp_path / "bad-lifecycle.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    # The generator selects its four fields and ignores evaluation metadata.
    assert agent.Fixture.from_file(path).fixture_id == payload["fixture_id"]
    # The learner-facing harness owns lifecycle selection and must fail closed.
    with pytest.raises(ValueError, match="invalid fixture lifecycle"):
        validate_harness_metadata(payload)
