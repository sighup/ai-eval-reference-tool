"""Shared plumbing for the three-day lab: loading, rendering, and a little statistics.

Nothing in here decides whether a run is good. That is what graders, people and
judges do, and each of them has its own file. This module only answers "where are
the runs?", "what did the run do?" and "how sure can I be about a rate?".
"""

from __future__ import annotations

import csv
import glob
import json
import math
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

LAB = Path(__file__).resolve().parent
COURSE = LAB.parent  # three-day/
ROOT = COURSE.parent  # the repository root
CASES_DIR = COURSE / "cases"
WORK = COURSE / "work"
RESULTS = WORK / "results"
DEFAULT_TRACES = "three-day/traces/baseline.jsonl"


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def load_cases() -> dict[str, dict[str, Any]]:
    """Every case in ``three-day/cases/``, keyed by fixture id."""
    cases = {}
    for path in sorted(CASES_DIR.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        cases[case["fixture_id"]] = case
    return cases


def resolve(pattern: str) -> list[Path]:
    """Expand a glob relative to the repo root (or absolute). Sorted, de-duplicated."""
    base = pattern if Path(pattern).is_absolute() else str(ROOT / pattern)
    paths = sorted({Path(p) for p in glob.glob(base)})
    if not paths:
        raise FileNotFoundError(f"No trace files match {pattern!r}")
    return paths


def load_runs(*patterns: str) -> list[dict[str, Any]]:
    """Every run in every JSONL file matching the patterns, in a stable order.

    If a trace file has an ``<name>.effects.jsonl`` beside it (``record.py``
    writes one), each run gets ``run["effects"]``: the refunds, cancellations
    and escalations the run wrote to its database.
    """
    runs = []
    for pattern in patterns or (DEFAULT_TRACES,):
        for path in resolve(pattern):
            if path.name.endswith(".effects.jsonl"):
                continue
            effects = {}
            sidecar = path.with_name(path.stem + ".effects.jsonl")
            if sidecar.is_file():
                for line in sidecar.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        row = json.loads(line)
                        effects[row["run_id"]] = row
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    run = json.loads(line)
                    if run["run_id"] in effects:
                        run["effects"] = effects[run["run_id"]]
                    runs.append(run)
    return sorted(runs, key=lambda r: r["run_id"])


# --------------------------------------------------------------------------- #
# The shop's database (the seed every run starts from). Read-only here.
# --------------------------------------------------------------------------- #

SEED_DB = COURSE / "db" / "northwind.db"


@lru_cache(maxsize=1)
def _db() -> sqlite3.Connection:
    if not SEED_DB.is_file():
        raise SystemExit("No database yet. Build it with: uv run python three-day/db/seed.py")
    db = sqlite3.connect(f"file:{SEED_DB}?mode=ro", uri=True, check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db


def order(order_id: str) -> dict[str, Any] | None:
    """An order as the database holds it, with its owner's customer_id. None if unknown."""
    row = _db().execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    return dict(row) if row else None


def customer(customer_id: str) -> dict[str, Any] | None:
    """A customer's name, email and every street address they have had."""
    row = _db().execute(
        "SELECT * FROM customers WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    if row is None:
        return None
    lines = [
        r["line1"]
        for r in _db().execute(
            "SELECT line1 FROM addresses WHERE customer_id = ? ORDER BY valid_from",
            (customer_id,),
        )
    ]
    return {"customer_id": customer_id, "name": row["name"], "email": row["email"],
            "address_lines": lines}


def query(sql: str, *params: Any) -> list[dict[str, Any]]:
    """Run a read-only SQL query against the seed database."""
    return [dict(r) for r in _db().execute(sql, params)]


def split_of(run_id: str) -> str:
    """``dev``, ``test`` or ``rest``, fixed by the run's number so it never changes.

    Every case was run five times. You label two of them:

    * run 01 of every case is **dev**: label it on Day 2, and look at it as much
      as you like while you build a judge;
    * run 02 of every case is **test**: label it on Day 3, then score the judge
      on it once, at the end;
    * runs 03 and up are the **rest**: nobody labels them. They stand in for the
      traffic you will never have time to read, which is what a judge is for.

    The split is by run rather than by case so every half holds every case.
    """
    tail = run_id.rsplit("-", 1)[-1]
    if not tail.isdigit():
        return "rest"
    return {1: "dev", 2: "test"}.get(int(tail), "rest")


# --------------------------------------------------------------------------- #
# Reading a run
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    is_error: bool


def tool_calls(run: dict[str, Any]) -> list[ToolCall]:
    """The tool calls a run made, each paired with what the tool returned."""
    results = {}
    for step in run["steps"]:
        for obs in step.get("observations") or []:
            results[obs["source_call_id"]] = obs
    calls = []
    for step in run["steps"]:
        for call in step.get("tool_calls") or []:
            obs = results.get(call["tool_call_id"], {})
            calls.append(
                ToolCall(
                    name=call["name"],
                    arguments=call["arguments"],
                    result=obs.get("content", {}),
                    is_error=bool(obs.get("is_error")),
                )
            )
    return calls


def customer_text(run: dict[str, Any]) -> str:
    """Everything the customer was shown: each agent message, joined.

    Not just ``final_output``. When an agent talks and calls a tool in the same
    turn, that text reached the customer too.
    """
    parts = [s.get("message", "") for s in run["steps"] if s.get("source") == "agent"]
    return "\n\n".join(p for p in parts if p).strip() or run.get("final_output", "")


def as_of(run: dict[str, Any]) -> str:
    """The agent's notion of today, read back out of the rendered system prompt."""
    marker = "Today's date is "
    system = run["prompt"]["system"]
    start = system.find(marker)
    return system[start + len(marker) : start + len(marker) + 10] if start >= 0 else "unknown"


def customer_name(customer_id: str) -> str:
    """The signed-in customer's name, from the shop's own records.

    A reviewer needs it to notice when a reply describes somebody else.
    """
    found = customer(customer_id)
    return found["name"] if found else "name unknown"


def render(run: dict[str, Any], *, policies: bool = True) -> str:
    """A run as plain text a person, or a judge, can read top to bottom."""
    user = next(s for s in run["steps"] if s.get("source") == "user")
    asking = run["input"]["customer_id"]
    lines = [
        f"RUN {run['run_id']}  (case: {run['fixture_id']}, today: {as_of(run)}, "
        f"signed-in customer: {asking}, {customer_name(asking)})",
        "",
        "CUSTOMER MESSAGE",
        user["message"],
        "",
    ]
    if policies:
        lines.append("POLICY EXCERPTS THE AGENT WAS GIVEN")
        for doc in user.get("retrieved") or []:
            lines += [f"--- {doc['doc_id']}", doc["text"].strip()]
        lines.append("")
    lines.append("WHAT THE AGENT DID")
    calls = tool_calls(run)
    if not calls:
        lines.append("(no tool calls)")
    for i, call in enumerate(calls, 1):
        lines.append(f"{i}. {call.name}({json.dumps(call.arguments, ensure_ascii=False)})")
        tag = "ERROR" if call.is_error else "returned"
        lines.append(f"   {tag}: {json.dumps(call.result, ensure_ascii=False)}")
    lines += ["", f"WHAT THE AGENT SAID (stop reason: {run['stop_reason']})", customer_text(run)]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Labels
# --------------------------------------------------------------------------- #

LABEL_FIELDS = ["run_id", "fixture_id", "label", "failure_mode", "note"]


def read_labels(path: Path) -> dict[str, dict[str, str]]:
    """A labels CSV as ``{run_id: row}``. Rows with an empty label are skipped."""
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["run_id"]: row for row in csv.DictReader(handle) if row.get("label")}


def tags(row: dict[str, str]) -> list[str]:
    """A label's failure modes. One run can fail for several reasons: separate with ``;``."""
    return [t.strip() for t in (row.get("failure_mode") or "").split(";") if t.strip()]


def write_labels(path: Path, rows: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for run_id in sorted(rows):
            writer.writerow(rows[run_id])


# --------------------------------------------------------------------------- #
# Statistics: the four numbers this course uses
# --------------------------------------------------------------------------- #


def wilson(passes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for a pass rate.

    Use this instead of "plus or minus" arithmetic: it behaves at 0/5 and 5/5,
    which is exactly where small evals live.
    """
    if n == 0:
        return (0.0, 1.0)
    p = passes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def fmt_rate(passes: int, n: int) -> str:
    if n == 0:
        return "  n/a"
    lo, hi = wilson(passes, n)
    return f"{passes:>2}/{n:<2} {passes / n:>4.0%}  [{lo:.0%}–{hi:.0%}]"


@dataclass(frozen=True)
class Agreement:
    """How well a grader (or a second person) matches a reference set of labels.

    "Positive" here means *pass*, so:
    - TPR: of the runs the reference passed, the share this grader also passed.
    - TNR: of the runs the reference failed, the share this grader also failed.
    A grader that passes everything has TPR 100% and TNR 0%, and looks great on
    raw agreement whenever most runs pass. That is why we report all of them.
    """

    both_pass: int
    both_fail: int
    grader_pass_ref_fail: int  # the dangerous cell: a failure waved through
    grader_fail_ref_pass: int  # the annoying cell: a false alarm

    @property
    def n(self) -> int:
        return (
            self.both_pass + self.both_fail + self.grader_pass_ref_fail + self.grader_fail_ref_pass
        )

    @property
    def raw(self) -> float:
        return (self.both_pass + self.both_fail) / self.n if self.n else float("nan")

    @property
    def tpr(self) -> float:
        d = self.both_pass + self.grader_fail_ref_pass
        return self.both_pass / d if d else float("nan")

    @property
    def tnr(self) -> float:
        d = self.both_fail + self.grader_pass_ref_fail
        return self.both_fail / d if d else float("nan")

    @property
    def kappa(self) -> float:
        """Cohen's kappa: agreement beyond what two coin-flippers with these
        pass rates would reach by luck. 0 is chance, 1 is perfect; above ~0.6 is
        usually called substantial, above ~0.8 almost perfect."""
        n = self.n
        if not n:
            return float("nan")
        p_obs = self.raw
        g_pass = (self.both_pass + self.grader_pass_ref_fail) / n
        r_pass = (self.both_pass + self.grader_fail_ref_pass) / n
        p_exp = g_pass * r_pass + (1 - g_pass) * (1 - r_pass)
        return 1.0 if p_exp == 1 else (p_obs - p_exp) / (1 - p_exp)


def agreement(grader: dict[str, bool], reference: dict[str, bool]) -> Agreement:
    """Compare two ``{run_id: passed}`` maps on the runs they share."""
    shared = sorted(set(grader) & set(reference))
    cells = {"pp": 0, "ff": 0, "pf": 0, "fp": 0}
    for run_id in shared:
        key = ("p" if grader[run_id] else "f") + ("p" if reference[run_id] else "f")
        cells[key] += 1
    return Agreement(cells["pp"], cells["ff"], cells["pf"], cells["fp"])


def corrected_pass_rate(observed: float, tpr: float, tnr: float) -> float | None:
    """The true pass rate implied by a judge's observed rate and its known errors.

    If a judge passes 70% of runs, but you measured that it lets 40% of real
    failures through, the real pass rate is lower than 70%. This is the
    Rogan–Gladen correction from epidemiology, where a diagnostic test with
    known sensitivity and specificity is used to estimate prevalence. Returns
    None when the judge is no better than chance (TPR + TNR <= 1): then the
    judge's number tells you nothing at all.
    """
    if math.isnan(tpr) or math.isnan(tnr) or tpr + tnr <= 1:
        return None
    return min(1.0, max(0.0, (observed + tnr - 1) / (tpr + tnr - 1)))


def print_agreement(a: Agreement, grader_name: str, reference_name: str) -> None:
    print(f"\n{grader_name} vs {reference_name}  (n={a.n})")
    print(f"{'':24}{reference_name + ' pass':>16}{reference_name + ' fail':>16}")
    print(f"{grader_name + ' pass':24}{a.both_pass:>16}{a.grader_pass_ref_fail:>16}")
    print(f"{grader_name + ' fail':24}{a.grader_fail_ref_pass:>16}{a.both_fail:>16}")
    print(
        f"\nraw agreement {a.raw:.0%}   TPR {a.tpr:.0%}   TNR {a.tnr:.0%}   "
        f"Cohen's kappa {a.kappa:.2f}"
    )
