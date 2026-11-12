"""How far do two sets of pass/fail labels agree, and where exactly do they differ?

    uv run python three-day/lab/agree.py three-day/work/labels.csv three-day/answer-key/labels.csv
    uv run python three-day/lab/agree.py three-day/work/labels-sam.csv three-day/work/labels.csv

The first file is treated as the grader and the second as the reference, which
only matters for which way round TPR and TNR read. For two people, kappa is
the number to quote: it is symmetric, and it discounts agreement by luck.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from common import agreement, print_agreement, read_labels, tags


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    args = parser.parse_args()

    a_rows, b_rows = read_labels(args.first), read_labels(args.second)
    a = {r: row["label"] == "pass" for r, row in a_rows.items()}
    b = {r: row["label"] == "pass" for r, row in b_rows.items()}
    only = set(a) ^ set(b)
    if only:
        print(f"Note: {len(only)} runs are labelled in only one file and are left out.")

    print_agreement(agreement(a, b), args.first.stem, args.second.stem)

    differ = sorted(r for r in set(a) & set(b) if a[r] != b[r])
    if differ:
        print(
            f"\n{len(differ)} disagreements. Read both notes, then decide which criterion "
            "was unclear:"
        )
    for r in differ:
        print(f"\n  {r}")
        for name, rows in ((args.first.stem, a_rows), (args.second.stem, b_rows)):
            row = rows[r]
            tag = f" [{row['failure_mode']}]" if row.get("failure_mode") else ""
            print(f"    {name}: {row['label']}{tag} — {row.get('note', '')}")

    for name, rows in ((args.first.stem, a_rows), (args.second.stem, b_rows)):
        modes = Counter(
            t
            for row in rows.values()
            if row["label"] == "fail"
            for t in (tags(row) or ["(untagged)"])
        )
        if modes:
            print(
                f"\nFailure modes in {name}: "
                + ", ".join(f"{m} ×{c}" for m, c in modes.most_common())
            )


if __name__ == "__main__":
    main()
