"""Label runs by hand: read each one, decide pass or fail, say why in one sentence.

    uv run python three-day/lab/label.py                  # Day 2: dev (run 01 of each case)
    uv run python three-day/lab/label.py --split test     # Day 3: the test split (run 02)
    uv run python three-day/lab/label.py --show run-order-status-01
    uv run python three-day/lab/label.py --out three-day/work/labels-sam.csv

Saves after every answer, so you can quit and come back. Runs are shown in a
shuffled order (the same shuffle every time) so you do not grade five copies
of one case back to back and start skimming.

This deliberately does not show you what the code graders said. Look first,
then compare: the point is to find what the graders cannot see.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from common import WORK, load_runs, read_labels, render, split_of, tags, write_labels

RULE = "=" * 78


def ask(prompt: str, allowed: set[str] | None = None) -> str:
    while True:
        try:
            answer = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit("\nStopped. Every answer so far is saved.") from None
        if allowed is None or answer.lower() in allowed:
            return answer
        print(f"  please type one of: {', '.join(sorted(allowed))}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "traces", nargs="*", help="trace globs (default: three-day/traces/baseline.jsonl)"
    )
    parser.add_argument(
        "--split",
        default="dev",
        choices=["dev", "test", "rest", "all"],
        help="which runs to label (default: dev)",
    )
    parser.add_argument("--out", type=Path, default=WORK / "labels.csv", help="labels CSV to write")
    parser.add_argument("--show", metavar="RUN_ID", help="print one run and exit")
    parser.add_argument("--redo", action="store_true", help="also revisit runs already labelled")
    parser.add_argument("--no-policies", action="store_true", help="hide the policy excerpts")
    args = parser.parse_args()

    runs = load_runs(*args.traces)
    if args.show:
        match = [r for r in runs if r["run_id"] == args.show]
        if not match:
            raise SystemExit(f"No run {args.show!r} in those traces")
        print(render(match[0], policies=not args.no_policies))
        return

    labels = read_labels(args.out)
    queue = [
        r
        for r in runs
        if (args.redo or r["run_id"] not in labels)
        and (args.split == "all" or split_of(r["run_id"]) == args.split)
    ]
    random.Random(7).shuffle(queue)
    print(f"{len(labels)} labelled already, {len(queue)} to go. Writing to {args.out}\n")

    for i, run in enumerate(queue, 1):
        print(RULE)
        print(f"[{i}/{len(queue)}]")
        print(render(run, policies=not args.no_policies))
        print(RULE)
        verdict = ask(
            "Pass or fail?  p / f   (s = skip, q = save and quit): ", {"p", "f", "s", "q"}
        )
        if verdict == "q":
            break
        if verdict == "s":
            continue
        modes = sorted({t for row in labels.values() for t in tags(row)})
        mode = ""
        if verdict == "f":
            hint = f" (used so far: {', '.join(modes)})" if modes else ""
            mode = ask(f"Failure mode: a short tag, several separated by ;{hint}: ")
        note = ask("One sentence: what is wrong, or why it is fine: ")
        labels[run["run_id"]] = {
            "run_id": run["run_id"],
            "fixture_id": run["fixture_id"],
            "label": "pass" if verdict == "p" else "fail",
            "failure_mode": mode,
            "note": note,
        }
        write_labels(args.out, labels)

    passes = sum(row["label"] == "pass" for row in labels.values())
    print(f"\n{len(labels)} labelled: {passes} pass, {len(labels) - passes} fail. Saved {args.out}")


if __name__ == "__main__":
    main()
