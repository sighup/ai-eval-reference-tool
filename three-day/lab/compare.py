"""Did my change help? Score two sets of runs the same way, side by side.

    uv run python three-day/lab/compare.py traces/before.jsonl traces/after.jsonl
    uv run python three-day/lab/compare.py traces/before.jsonl traces/after.jsonl \
        --judge three-day/work/judges/wrong-fact.md

Every code grader runs on both. With ``--judge``, the judge does too (cached
verdicts are reused). Read the intervals, not just the rates: when they
overlap, five runs a case was not enough to tell.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from common import fmt_rate, load_runs, wilson
from grade import grade_runs, overall
from graders import GRADERS


def verdict_line(name: str, before: list[bool], after: list[bool]) -> str:
    b_lo, b_hi = wilson(sum(before), len(before))
    a_lo, a_hi = wilson(sum(after), len(after))
    if not before or not after:
        call = ""
    elif a_lo > b_hi:
        call = "better"
    elif a_hi < b_lo:
        call = "WORSE"
    else:
        call = "can't tell"
    rates = f"{fmt_rate(sum(before), len(before)):>24}{fmt_rate(sum(after), len(after)):>24}"
    return f"  {name:30}{rates}   {call}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--judge", type=Path, help="also run this judge prompt on both")
    args = parser.parse_args()

    sides = {"before": load_runs(args.before), "after": load_runs(args.after)}
    graded = {side: grade_runs(runs) for side, runs in sides.items()}

    print(f"  {'':30}{'before':>24}{'after':>24}")
    for g in GRADERS:
        n = g.__name__
        vals = {
            side: [v[n].passed for v in graded[side].values() if v[n].passed is not None]
            for side in sides
        }
        print(verdict_line(n, vals["before"], vals["after"]))

    if args.judge:
        from judge import judge_runs  # noqa: PLC0415 - only needed with --judge

        template = args.judge.read_text(encoding="utf-8")
        judged = {side: judge_runs(runs, template) for side, runs in sides.items()}
        vals = {
            side: [r["verdict"] == "pass" for r in judged[side].values() if r["verdict"]]
            for side in sides
        }
        print(verdict_line(f"judge: {args.judge.stem}", vals["before"], vals["after"]))

    print()
    by_case: dict[str, dict[str, list[bool]]] = defaultdict(lambda: {"before": [], "after": []})
    for side, runs in sides.items():
        for run in runs:
            by_case[run["fixture_id"]][side].append(overall(graded[side][run["run_id"]]))
    for case, vals in sorted(by_case.items()):
        print(verdict_line(case, vals["before"], vals["after"]))
    totals = {side: [overall(v) for v in graded[side].values()] for side in sides}
    print(verdict_line("ALL RUNS (code graders)", totals["before"], totals["after"]))


if __name__ == "__main__":
    main()
