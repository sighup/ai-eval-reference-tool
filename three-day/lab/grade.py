"""Run every code grader over a set of traces and summarise.

    uv run python three-day/lab/grade.py                      # the 190 baseline runs
    uv run python three-day/lab/grade.py three-day/traces/after.jsonl   # your own runs
    uv run python three-day/lab/grade.py --why                # print every failure reason
    uv run python three-day/lab/grade.py --split dev          # only runs numbered 01
    uv run python three-day/lab/grade.py --all                # list passing runs too
    uv run python three-day/lab/grade.py --labels three-day/work/labels.csv

A run passes overall when no grader failed it. Graders that return None for a
run (not applicable, or not written yet) do not count either way.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Any

from common import (
    RESULTS,
    agreement,
    fmt_rate,
    load_cases,
    load_runs,
    print_agreement,
    read_labels,
    split_of,
)
from graders import GRADERS, Grader, Verdict


def grade_runs(
    runs: list[dict[str, Any]], graders: list[Grader] = GRADERS
) -> dict[str, dict[str, Verdict]]:
    """``{run_id: {grader_name: Verdict}}`` for every run."""
    cases = load_cases()
    out: dict[str, dict[str, Verdict]] = {}
    for run in runs:
        case = cases.get(run["fixture_id"])
        if case is None:
            raise SystemExit(f"No case in three-day/cases/ for fixture {run['fixture_id']!r}")
        out[run["run_id"]] = {g.__name__: g(run, case) for g in graders}
    return out


def overall(verdicts: dict[str, Verdict]) -> bool:
    return all(v.passed is not False for v in verdicts.values())


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "traces", nargs="*", help="trace globs (default: three-day/traces/baseline.jsonl)"
    )
    parser.add_argument("--why", action="store_true", help="print the reason for every failure")
    parser.add_argument("--labels", type=Path, help="compare the overall verdict to human labels")
    parser.add_argument("--all", action="store_true", help="list every run, not only failures")
    parser.add_argument(
        "--split",
        choices=["dev", "test", "rest", "all"],
        default="all",
        help="only runs in this split (dev = 01, test = 02, rest = 03 and up)",
    )
    args = parser.parse_args()

    runs = [
        r
        for r in load_runs(*args.traces)
        if args.split == "all" or split_of(r["run_id"]) == args.split
    ]
    if not runs:
        raise SystemExit(f"no runs in the {args.split} split")
    graded = grade_runs(runs)
    names = [g.__name__ for g in GRADERS]
    mark = {True: "pass", False: "FAIL", None: "  · "}

    # 1. One row per run (only the failing ones unless --all).
    width = max(len(r) for r in graded) + 2
    shown = {r: v for r, v in graded.items() if args.all or not overall(v)}
    label = "run" if args.all else "failing runs"
    print(f"{label:{width}}" + "".join(f"{n[:14]:>16}" for n in names) + f"{'overall':>10}")
    for run_id, verdicts in shown.items():
        cells = "".join(f"{mark[verdicts[n].passed]:>16}" for n in names)
        print(f"{run_id:{width}}{cells}{'pass' if overall(verdicts) else 'FAIL':>10}")
        if args.why:
            for n in names:
                if verdicts[n].passed is False:
                    print(f"{'':{width}}  ↳ {n}: {verdicts[n].reason}")

    # 2. One row per grader.
    print("\nPer grader (runs where it applied)       pass rate  [95% CI]")
    for n in names:
        applied = [v for v in (graded[r][n] for r in graded) if v.passed is not None]
        passes = sum(v.passed for v in applied)
        note = "" if applied else "   (skipped everywhere: not written yet?)"
        print(f"  {n:38}{fmt_rate(passes, len(applied))}{note}")

    # 3. One row per case: this is where repeats show you flakiness.
    by_case: dict[str, list[bool]] = defaultdict(list)
    for run in runs:
        by_case[run["fixture_id"]].append(overall(graded[run["run_id"]]))
    print("\nPer case (overall verdict across repeats)")
    for case, results in sorted(by_case.items()):
        print(f"  {case:38}{fmt_rate(sum(results), len(results))}")
    total = [overall(v) for v in graded.values()]
    print(f"\n  {'ALL RUNS':38}{fmt_rate(sum(total), len(total))}")

    # 4. Save it, so Day 2 and Day 3 can compare against it.
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "code-grades.csv"
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["run_id", "grader", "passed", "reason"])
        for run_id, verdicts in graded.items():
            for n in names:
                writer.writerow([run_id, n, verdicts[n].passed, verdicts[n].reason])
            writer.writerow([run_id, "OVERALL", overall(verdicts), ""])
    print(f"\nWrote {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}")

    if args.labels:
        human = {r: row["label"] == "pass" for r, row in read_labels(args.labels).items()}
        code = {r: overall(v) for r, v in graded.items()}
        print_agreement(agreement(code, human), "code", "human")
        missed = sorted(r for r in code if r in human and code[r] and not human[r])
        if missed:
            print("\nFailures your graders waved through:")
            for r in missed:
                print(f"  {r}")


if __name__ == "__main__":
    main()
