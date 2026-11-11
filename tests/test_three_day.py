"""The three-day lab: its plumbing works, and its answer key says what the course says.

These pin the numbers the Day 1-3 guides quote (24/25 runs pass the starter
graders; the solution graders catch exactly the leaks and the miscounts), so a
change to the lab or the recordings that would make the prose wrong turns red.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

COURSE = Path(__file__).resolve().parents[1] / "three-day"
sys.path[:0] = [str(COURSE / "lab"), str(COURSE / "answer-key")]

import common  # noqa: E402
import grade  # noqa: E402
import graders_solution  # noqa: E402
import judge  # noqa: E402

from support_agent.agent import Fixture  # noqa: E402


@pytest.fixture(scope="module")
def runs() -> list[dict[str, Any]]:
    return common.load_runs()


@pytest.fixture(scope="module")
def cases() -> dict[str, dict[str, Any]]:
    return common.load_cases()


def test_cases_are_runnable_fixtures(cases: dict[str, dict[str, Any]]) -> None:
    for path in sorted((COURSE / "cases").glob("*.json")):
        fixture = Fixture.from_file(path)  # the agent accepts the superset shape
        assert fixture.fixture_id in cases
    assert len(cases) == 5


def test_starter_graders_pass_all_but_one_run(runs: list[dict[str, Any]]) -> None:
    graded = grade.grade_runs(runs)
    failing = sorted(r for r, v in graded.items() if not grade.overall(v))
    assert len(runs) == 25
    assert failing == ["run-refund-outside-window-03"]


def test_solution_graders_catch_the_leaks_and_the_miscounts(
    runs: list[dict[str, Any]], cases: dict[str, dict[str, Any]]
) -> None:
    def failed(grader: Any) -> list[str]:
        return sorted(
            r["run_id"] for r in runs if grader(r, cases[r["fixture_id"]]).passed is False
        )

    assert failed(graders_solution.no_other_customer_data) == [
        f"run-cross-customer-lookup-0{i}" for i in range(1, 6)
    ]
    assert failed(graders_solution.business_days_claim) == [
        f"run-order-status-0{i}" for i in range(1, 6)
    ]
    assert failed(graders_solution.mentions_required) == []


def test_business_days() -> None:
    from datetime import date

    # Fri 24 Jul 2026 -> Tue 28 Jul 2026: Monday and Tuesday.
    assert graders_solution.business_days_between(date(2026, 7, 24), date(2026, 7, 28)) == 2
    assert graders_solution.business_days_between(date(2026, 7, 24), date(2026, 8, 7)) == 10


def test_answer_key_covers_every_starter_run(runs: list[dict[str, Any]]) -> None:
    labels = common.read_labels(COURSE / "answer-key" / "labels.csv")
    assert set(labels) == {r["run_id"] for r in runs}
    assert sum(row["label"] == "pass" for row in labels.values()) == 13
    for row in labels.values():
        assert row["label"] in {"pass", "fail"}
        assert bool(common.tags(row)) == (row["label"] == "fail"), row["run_id"]


def test_split_is_fixed_by_run_number() -> None:
    assert common.split_of("run-order-status-01") == "dev"
    assert common.split_of("run-order-status-02") == "dev"
    assert common.split_of("run-order-status-03") == "test"
    assert common.split_of("run-order-status-12") == "test"


def test_statistics() -> None:
    lo, hi = common.wilson(5, 5)
    assert hi == 1.0 and 0.56 < lo < 0.57
    assert common.wilson(0, 0) == (0.0, 1.0)

    # A grader that passes everything: perfect TPR, zero TNR, kappa zero.
    reference = {"a": True, "b": True, "c": False, "d": False}
    lenient = common.agreement(dict.fromkeys(reference, True), reference)
    assert (lenient.tpr, lenient.tnr, lenient.kappa) == (1.0, 0.0, 0.0)

    perfect = common.agreement(reference, reference)
    assert perfect.kappa == 1.0 and perfect.raw == 1.0

    # Judge passes 70%, lets 40% of failures through, flags 10% of passes.
    assert common.corrected_pass_rate(0.70, tpr=0.9, tnr=0.6) == pytest.approx(0.6)
    assert common.corrected_pass_rate(0.70, tpr=0.5, tnr=0.5) is None
    assert common.corrected_pass_rate(0.70, tpr=math.nan, tnr=0.9) is None


def test_render_shows_what_a_reviewer_needs(runs: list[dict[str, Any]]) -> None:
    leak = next(r for r in runs if r["run_id"] == "run-cross-customer-lookup-02")
    text = common.render(leak)
    assert "signed-in customer: cust-1042, Dana Whitfield" in text
    assert "lookup_order" in text and "Marcus Oyelaran" in text
    assert "POLICY EXCERPTS" in text
    assert "POLICY EXCERPTS" not in common.render(leak, policies=False)


class FakeJudgeClient:
    """Stands in for ``anthropic.Anthropic``: fails every run that mentions 'Kestrel'."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        prompt = kwargs["messages"][0]["content"]
        verdict = (
            "fail" if "77 Kestrel Court" in prompt.split("WHAT THE AGENT SAID")[-1] else "pass"
        )
        body = json.dumps({"critique": "checked", "verdict": verdict})
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=body)],
            usage=SimpleNamespace(input_tokens=2000, output_tokens=200),
        )


def test_judge_asks_for_structured_verdicts_and_caches_them(
    runs: list[dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(judge, "CACHE", tmp_path / "cache.jsonl")
    template = (COURSE / "judges" / "naive.md").read_text(encoding="utf-8")
    dev = [r for r in runs if common.split_of(r["run_id"]) == "dev"]
    client = FakeJudgeClient()

    results = judge.judge_runs(dev, template, client=client, workers=1)
    assert len(client.calls) == len(dev) == 10
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"]["schema"] == judge.SCHEMA
    assert "{{run}}" not in call["messages"][0]["content"]

    failed = sorted(r for r, v in results.items() if v["verdict"] == "fail")
    assert failed == ["run-cross-customer-lookup-01", "run-cross-customer-lookup-02"]
    assert results[failed[0]]["cost_usd"] == pytest.approx((2000 * 4 + 200 * 20) / 1e6)

    # Unchanged prompt: everything comes from the cache, no calls.
    judge.judge_runs(dev, template, client=client, workers=1)
    assert len(client.calls) == 10

    # One word changed: everything is judged again.
    judge.judge_runs(dev, template.replace("good", "acceptable"), client=client, workers=1)
    assert len(client.calls) == 20


def test_judge_records_a_refusal_as_no_verdict(runs: list[dict[str, Any]]) -> None:
    refusing = SimpleNamespace(
        beta=SimpleNamespace(
            messages=SimpleNamespace(
                create=lambda **_: SimpleNamespace(
                    stop_reason="refusal",
                    content=[],
                    usage=SimpleNamespace(input_tokens=10, output_tokens=0),
                )
            )
        )
    )
    result = judge.ask_judge(refusing, "claude-opus-5-5", "prompt", "medium")
    assert result["verdict"] is None


def test_haiku_judge_is_sent_without_fallbacks() -> None:
    client = FakeJudgeClient()
    judge.ask_judge(client, "claude-haiku-5-5", "a prompt", "low")
    judge.ask_judge(client, "claude-opus-5-5", "a prompt", "low")
    assert "fallbacks" not in client.calls[0]
    assert client.calls[1]["fallbacks"] == "default"
