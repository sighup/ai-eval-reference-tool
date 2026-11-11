"""The three-day lab: its plumbing works, and its answer key says what the course says.

These pin the numbers the Day 1-3 guides quote (175/190 runs pass the starter
graders, 150/190 after Day 1, 30/38 on dev; the solution graders catch exactly
the leaks and the retrieval misses), so a change to the lab or the recordings
that would make the prose wrong turns red. They need the seed database
(``three-day/db/seed.py``), which they build if it is missing.
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
sys.path[:0] = [str(COURSE / "lab"), str(COURSE / "answer-key"), str(COURSE / "db")]

if not (COURSE / "db" / "northwind.db").is_file():
    import seed  # noqa: E402

    seed.build(COURSE / "db" / "northwind.db")

import common  # noqa: E402
import grade  # noqa: E402
import graders  # noqa: E402
import graders_solution as sol  # noqa: E402
import judge  # noqa: E402
import score  # noqa: E402

from support_agent.agent import Fixture  # noqa: E402

DAY1 = [
    graders.required_tools,
    graders.forbidden_tools,
    graders.refund_within_limit,
    sol.mentions_required,
    sol.no_other_customer_data,
    sol.policy_retrieved,
]


@pytest.fixture(scope="module")
def runs() -> list[dict[str, Any]]:
    return common.load_runs()


@pytest.fixture(scope="module")
def cases() -> dict[str, dict[str, Any]]:
    return common.load_cases()


def _passing(runs: list[dict[str, Any]], graders_: list[Any]) -> dict[str, bool]:
    return {r: grade.overall(v) for r, v in grade.grade_runs(runs, graders_).items()}


def test_cases_are_runnable_fixtures(cases: dict[str, dict[str, Any]]) -> None:
    for path in sorted((COURSE / "cases").glob("*.json")):
        fixture = Fixture.from_file(path)  # the agent accepts the superset shape
        assert fixture.fixture_id in cases
    assert len(cases) == 38
    splits = [c["metadata"]["climb_split"] for c in cases.values()]
    assert splits.count("climb") == 26 and splits.count("holdout") == 12


def test_starter_and_day1_numbers(runs: list[dict[str, Any]]) -> None:
    assert len(runs) == 190
    assert all("effects" in r for r in runs)
    assert sum(_passing(runs, grade.GRADERS).values()) == 175  # stubs are skipped
    day1 = _passing(runs, DAY1)
    assert sum(day1.values()) == 150
    dev = [r for r in day1 if common.split_of(r) == "dev"]
    assert len(dev) == 38 and sum(day1[r] for r in dev) == 30


def test_solution_graders_catch_the_leaks_and_the_misses(
    runs: list[dict[str, Any]], cases: dict[str, dict[str, Any]]
) -> None:
    def failed(grader: Any) -> list[str]:
        return sorted(
            r["run_id"] for r in runs if grader(r, cases[r["fixture_id"]]).passed is False
        )

    five = lambda case: [f"run-{case}-0{i}" for i in range(1, 6)]  # noqa: E731
    assert failed(sol.no_other_customer_data) == five("cross-customer-lookup")
    assert failed(sol.no_other_customers_order_details) == (
        five("cross-customer-lookup") + five("privacy-refund-other") + five("privacy-typo-order")
    )
    assert failed(sol.policy_retrieved) == sorted(
        five("refund-already-done")
        + five("status-lost-parcel")
        + five("status-no-order-id")
        + five("status-processing-today")
    )
    assert failed(sol.mentions_required) == []
    assert failed(sol.claims_match_database) == []


def test_business_days() -> None:
    from datetime import date

    # Fri 24 Jul 2026 -> Tue 28 Jul 2026: Monday and Tuesday.
    assert sol.business_days_between(date(2026, 7, 24), date(2026, 7, 28)) == 2
    assert sol.business_days_between(date(2026, 7, 24), date(2026, 8, 7)) == 10


def test_answer_key_labels_dev_and_test(runs: list[dict[str, Any]]) -> None:
    labels = common.read_labels(COURSE / "answer-key" / "labels.csv")
    labelled = {r["run_id"] for r in runs if common.split_of(r["run_id"]) in {"dev", "test"}}
    assert set(labels) == labelled
    by_split = {"dev": 0, "test": 0}
    for run_id, row in labels.items():
        assert row["label"] in {"pass", "fail"}
        assert bool(common.tags(row)) == (row["label"] == "fail"), run_id
        by_split[common.split_of(run_id)] += row["label"] == "pass"
    assert by_split == {"dev": 31, "test": 30}


def test_split_is_fixed_by_run_number() -> None:
    assert common.split_of("run-order-status-01") == "dev"
    assert common.split_of("run-order-status-02") == "test"
    assert common.split_of("run-order-status-03") == "rest"
    assert common.split_of("run-order-status-12") == "rest"


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
    leak = next(r for r in runs if r["run_id"] == "run-cross-customer-lookup-01")
    text = common.render(leak)
    assert "signed-in customer: cust-1042, Dana Whitfield" in text
    assert "lookup_order" in text and "B-5510" in text
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
    assert len(client.calls) == len(dev) == 38
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"]["schema"] == judge.SCHEMA
    assert "{{run}}" not in call["messages"][0]["content"]

    failed = sorted(r for r, v in results.items() if v["verdict"] == "fail")
    assert failed == ["run-cross-customer-lookup-01"]
    assert results[failed[0]]["cost_usd"] == pytest.approx((2000 * 4 + 200 * 20) / 1e6)

    # Unchanged prompt: everything comes from the cache, no calls.
    judge.judge_runs(dev, template, client=client, workers=1)
    assert len(client.calls) == 38

    # One word changed: everything is judged again.
    judge.judge_runs(dev, template.replace("good", "acceptable"), client=client, workers=1)
    assert len(client.calls) == 76


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


def test_score_logs_and_compares(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(score, "LOG", tmp_path / "climb-log.csv")
    trace = str(COURSE / "traces" / "baseline.jsonl")
    score.main([trace, "--note", "first"])
    first = capsys.readouterr().out
    assert "190 runs (mixed cases), 0 judge(s)" in first
    assert first.rstrip().endswith("SCORE 0.9211")  # 175/190 with the stubs skipped
    score.main([trace, "--note", "again"])
    again = capsys.readouterr().out
    assert "best so far on mixed: 92.1%" in again and "can't tell from noise" in again
    rows = (tmp_path / "climb-log.csv").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 3 and "refund-partial-item=0/5" in rows[1]
