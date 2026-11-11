"""One number for a set of runs, for hill-climbing.

    uv run python three-day/lab/score.py three-day/traces/climb-01.jsonl \
        --judge three-day/work/judges/grounded.md --note "scope lookup_order to the customer"

A run passes when no code grader and no judge you list fails it. The score is
the share of runs that pass, with its 95% interval. Guardrails are reported
separately: a change that raises the score but lets one more privacy leak or
over-refund through is not an improvement, whatever the score says.

Every call appends a row to ``three-day/work/results/climb-log.csv`` with the git
commit, the score and your note, and prints the best score so far on the same
cases. The last line is ``SCORE <number>``, so a loop (or the autoresearch
plugin) can read it.

Each call also compares the score with the first one logged on the same cases
and judges (your baseline) and with the best so far, and lists the cases that now pass more
or less often than at the best.

A single change rarely moves the score beyond the noise on its own: 78 runs give
an interval about 20 points wide. So keep a change when

1. it is not WORSE than the best, beyond the noise,
2. no guardrail got worse, and
3. the cases it moved are the ones you meant it to move.

The climb as a whole should beat the baseline beyond the noise. Then score the
holdout cases once.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common import RESULTS, ROOT, fmt_rate, load_cases, load_runs, wilson
from grade import grade_runs
from graders import GRADERS

#: Graders that must never get worse, however the score moves.
GUARDRAILS = ["no_other_customer_data", "refund_within_limit"]
LOG = RESULTS / "climb-log.csv"
FIELDS = [
    "when",
    "commit",
    "cases",
    "runs",
    "passes",
    "score",
    "low",
    "high",
    "guardrails",
    "judges",
    "traces",
    "note",
    "per_case",
]


def git_commit() -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", "three-day/agent", "src/support_agent"],
            capture_output=True,
            text=True,
            cwd=ROOT,
        ).stdout.strip()
        return sha + ("+changes" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def score_runs(
    runs: list[dict[str, Any]],
    judges: list[Path],
    judge_model: str | None = None,
    via: str = "auto",
) -> tuple[dict[str, bool], dict[str, tuple[int, int]]]:
    """``({run_id: passed}, {guardrail: (passes, applicable)})``."""
    graded = grade_runs(runs, GRADERS)
    passed = {r: all(v.passed is not False for v in vs.values()) for r, vs in graded.items()}
    guards = {}
    for name in GUARDRAILS:
        applied = [vs[name].passed for vs in graded.values() if vs[name].passed is not None]
        guards[name] = (sum(applied), len(applied))
    for path in judges:
        from judge import DEFAULT_MODEL, judge_runs  # noqa: PLC0415 - only when judging

        results = judge_runs(
            runs, path.read_text(encoding="utf-8"), model=judge_model or DEFAULT_MODEL, via=via
        )
        for run_id, result in results.items():
            if result["verdict"] == "fail":
                passed[run_id] = False
    return passed, guards


def logged(cases: str, judges: str) -> list[dict[str, str]]:
    """Earlier rows scored the same way: same cases, same judges."""
    if not LOG.is_file():
        return []
    with LOG.open(encoding="utf-8") as fh:
        return [
            r for r in csv.DictReader(fh) if r["cases"] == cases and r.get("judges", "") == judges
        ]


def by_case(passed: dict[str, bool]) -> dict[str, tuple[int, int]]:
    """``{fixture: (passes, runs)}``; run ids are ``run-<fixture>-<nn>``."""
    out: dict[str, tuple[int, int]] = {}
    for run_id, ok in passed.items():
        fixture = run_id.rsplit("-", 1)[0].removeprefix("run-")
        p, n = out.get(fixture, (0, 0))
        out[fixture] = (p + ok, n + 1)
    return out


def _parse_cases(text: str) -> dict[str, float]:
    out = {}
    for item in filter(None, (text or "").split(";")):
        name, frac = item.split("=")
        p, n = (int(x) for x in frac.split("/"))
        out[name] = p / n
    return out


def compare(label: str, row: dict[str, str], low: float, high: float) -> None:
    print(
        f"{label}: {float(row['score']):.1%} "
        f"[{float(row['low']):.0%}–{float(row['high']):.0%}] "
        f"at {row['commit']} ({row['note'] or 'no note'})"
    )
    if low > float(row["high"]):
        print("  -> better, beyond the noise")
    elif high < float(row["low"]):
        print("  -> WORSE, beyond the noise")
    else:
        print("  -> can't tell from noise")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("traces", nargs="+", help="trace files to score")
    parser.add_argument(
        "--judge",
        type=Path,
        action="append",
        default=[],
        help="a judge prompt whose fail also fails the run (repeatable)",
    )
    parser.add_argument("--judge-model", help="model for the judges (default: judge.py's)")
    parser.add_argument("--via", default="auto", choices=["auto", "api", "claude"])
    parser.add_argument("--note", default="", help="what you changed, for the log")
    args = parser.parse_args(argv)

    runs = load_runs(*args.traces)
    if not runs:
        raise SystemExit("no runs in those traces")
    cases = load_cases()
    splits = {cases[r["fixture_id"]]["metadata"].get("climb_split", "climb") for r in runs}
    which = splits.pop() if len(splits) == 1 else "mixed"

    judges = ";".join(p.name for p in args.judge)
    history = logged(which, judges)
    baseline = history[0] if history else None
    previous = max(history, key=lambda r: float(r["score"]), default=None)
    passed, guards = score_runs(runs, args.judge, args.judge_model, args.via)
    n, k = len(passed), sum(passed.values())
    low, high = wilson(k, n)
    score = k / n

    print(f"{len(runs)} runs ({which} cases), {len(args.judge)} judge(s)")
    print(f"  score          {fmt_rate(k, n)}")
    for name, (gp, ga) in guards.items():
        print(f"  guardrail      {name:28} {fmt_rate(gp, ga)}")
    cases_now = by_case(passed)
    worst = sorted(
        ((c, n - p) for c, (p, n) in cases_now.items() if p < n), key=lambda kv: (-kv[1], kv[0])
    )[:8]
    if worst:
        print("  most failures  " + ", ".join(f"{c} ({m})" for c, m in worst))

    if baseline and baseline is not previous:
        print()
        compare(f"baseline on {which}", baseline, low, high)
    if previous:
        print()
        compare(f"best so far on {which}", previous, low, high)
        before = _parse_cases(previous.get("per_case", ""))
        up = [c for c, (p, n) in sorted(cases_now.items()) if c in before and p / n > before[c]]
        down = [c for c, (p, n) in sorted(cases_now.items()) if c in before and p / n < before[c]]
        if up:
            print("  passes more often:  " + ", ".join(up))
        if down:
            print("  passes less often:  " + ", ".join(down))
        old_guards = dict(g.split("=") for g in previous["guardrails"].split(";") if g)
        for name, (gp, ga) in guards.items():
            if name in old_guards:
                op, oa = (int(x) for x in old_guards[name].split("/"))
                if oa and ga and gp / ga < op / oa:
                    print(f"  -> guardrail {name} got WORSE ({op}/{oa} -> {gp}/{ga})")

    RESULTS.mkdir(parents=True, exist_ok=True)
    new = not LOG.is_file()
    with LOG.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        writer.writerow(
            {
                "when": datetime.now(UTC).isoformat(timespec="seconds"),
                "commit": git_commit(),
                "cases": which,
                "runs": n,
                "passes": k,
                "score": f"{score:.4f}",
                "low": f"{low:.4f}",
                "high": f"{high:.4f}",
                "guardrails": ";".join(f"{g}={p}/{a}" for g, (p, a) in guards.items()),
                "judges": judges,
                "traces": ";".join(args.traces),
                "note": args.note,
                "per_case": ";".join(f"{c}={p}/{n}" for c, (p, n) in sorted(cases_now.items())),
            }
        )
    print(f"\nSCORE {score:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
