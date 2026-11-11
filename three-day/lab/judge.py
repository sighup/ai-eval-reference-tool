"""LLM-as-judge: ask a model to grade runs against a rubric you wrote, then
check the model against your own labels before you believe a word of it.

    # See exactly what the judge will be sent, and what it will cost. Free.
    uv run python three-day/lab/judge.py three-day/judges/naive.md --dry-run

    # Judge the dev split and compare with your labels.
    uv run python three-day/lab/judge.py three-day/judges/naive.md --split dev

    # A judge for one failure mode, compared against just that mode.
    uv run python three-day/lab/judge.py three-day/work/judges/wrong-fact.md \
        --split dev --mode wrong_fact

    # Once, at the very end: the held-out test split.
    uv run python three-day/lab/judge.py three-day/work/judges/wrong-fact.md \
        --split test --mode wrong_fact

A judge prompt is a Markdown file containing ``{{run}}``, which is replaced by
the run rendered as text (the same view ``label.py`` shows you). The judge must
answer with a short critique and then a verdict, ``pass`` or ``fail``; the
request enforces that shape, so your prompt only has to say what passing means.

Verdicts are cached in ``three-day/work/results/judge-cache.jsonl``, keyed by
the model, the exact prompt text and the run. Re-running an unchanged judge
costs nothing; changing one word of the prompt re-judges everything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import claude_cli
from common import (
    RESULTS,
    ROOT,
    WORK,
    agreement,
    corrected_pass_rate,
    fmt_rate,
    load_runs,
    print_agreement,
    read_labels,
    render,
    split_of,
    tags,
)

DEFAULT_MODEL = "claude-opus-5-5"

#: USD per million tokens, input and output. Check current prices before a big run.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}

#: The judge must return exactly this. Critique first, verdict second: a model
#: that has to explain itself before it commits is a better judge, and the
#: critique is what you read when it disagrees with you.
SCHEMA = {
    "type": "object",
    "properties": {
        "critique": {"type": "string"},
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
    },
    "required": ["critique", "verdict"],
    "additionalProperties": False,
}

CACHE = RESULTS / "judge-cache.jsonl"


def build_prompt(template: str, run: dict[str, Any]) -> str:
    if "{{run}}" not in template:
        raise SystemExit("The judge prompt must contain {{run}} where the run should go.")
    return template.replace("{{run}}", render(run))


def cache_key(model: str, prompt: str) -> str:
    return hashlib.sha256(f"{model}\n{prompt}".encode()).hexdigest()


def load_cache() -> dict[str, dict[str, Any]]:
    if not CACHE.is_file():
        return {}
    entries = (json.loads(line) for line in CACHE.read_text(encoding="utf-8").splitlines() if line)
    return {e["key"]: e for e in entries}


class ClaudeCodeJudge:
    """Asks the judge through Claude Code (``claude -p``) instead of the API.

    No API key needed: it uses whatever Claude Code is signed in with. Claude
    Code's own system prompt and tools are switched off, so the judge sees only
    your rubric, and ``--json-schema`` enforces the same critique-then-verdict
    shape as the API path. Cost is what Claude Code reports, which includes a
    little of its own overhead.
    """

    SYSTEM = (
        "You are an evaluator. Read the rubric and the run in the user's message and "
        "answer only in the required structured format."
    )

    def ask(self, model: str, prompt: str, effort: str) -> dict[str, Any]:
        cmd = claude_cli.base_command(model, system=["--system-prompt", self.SYSTEM])
        cmd += [
            "--tools",
            "",
            "--effort",
            effort,
            "--json-schema",
            json.dumps(SCHEMA),
            "--output-format",
            "json",
        ]
        proc = claude_cli.run(cmd, prompt)
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {
                "verdict": None,
                "critique": f"claude -p failed: {(proc.stderr or proc.stdout)[-300:]}",
                "cost_usd": 0.0,
            }
        cost = float(out.get("total_cost_usd") or 0.0)
        answer = out.get("structured_output")
        if not isinstance(answer, dict) or answer.get("verdict") not in {"pass", "fail"}:
            text = str(out.get("result", ""))[:200]
            return {"verdict": None, "critique": f"no structured answer: {text}", "cost_usd": cost}
        return {"verdict": answer["verdict"], "critique": answer["critique"], "cost_usd": cost}


def make_client(via: str = "auto") -> Any:
    """Who answers the judge: the API (needs a key) or Claude Code (does not).

    ``auto`` uses the API when ``ANTHROPIC_API_KEY`` is set, otherwise Claude Code.
    """
    sys.path.insert(0, str(ROOT / "src"))
    from support_agent import config  # noqa: PLC0415 - only needed for live calls

    if via == "auto":
        config.load_env()
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
        via = "api" if has_key or not shutil.which("claude") else "claude"
    if via == "claude":
        return ClaudeCodeJudge()

    import anthropic  # noqa: PLC0415

    return anthropic.Anthropic(api_key=config.api_key())


def ask_judge(client: Any, model: str, prompt: str, effort: str) -> dict[str, Any]:
    """One judge call. Returns ``{"verdict", "critique", "cost_usd"}``.

    ``fallbacks: "default"`` lets the API retry on another model if this one
    declines; a judge reading support transcripts should never trip that, but a
    red-team transcript one day might.
    """
    if isinstance(client, ClaudeCodeJudge):
        return client.ask(model, prompt, effort)
    extra: dict[str, Any] = {}
    if "haiku" not in model:  # Haiku has no server-side fallback
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
        **extra,
    )
    price_in, price_out = PRICES.get(model, PRICES[DEFAULT_MODEL])
    usage = response.usage
    cost = (usage.input_tokens * price_in + usage.output_tokens * price_out) / 1_000_000
    if response.stop_reason == "refusal":
        return {
            "verdict": None,
            "critique": "the model declined to judge this run",
            "cost_usd": cost,
        }
    text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
    try:
        answer = json.loads(text)
    except json.JSONDecodeError:
        return {"verdict": None, "critique": f"unparseable answer: {text[:200]}", "cost_usd": cost}
    return {"verdict": answer["verdict"], "critique": answer["critique"], "cost_usd": cost}


def judge_runs(
    runs: list[dict[str, Any]],
    template: str,
    *,
    model: str = DEFAULT_MODEL,
    effort: str = "medium",
    client: Any = None,
    workers: int = 4,
    via: str = "auto",
) -> dict[str, dict[str, Any]]:
    """Judge every run, using the cache where it can. ``{run_id: result}``."""
    cache = load_cache()
    prompts = {r["run_id"]: build_prompt(template, r) for r in runs}
    todo = [rid for rid, p in prompts.items() if cache_key(model, p) not in cache]
    if todo:
        client = client or make_client(via)
        print(f"Judging {len(todo)} runs with {model} ({len(runs) - len(todo)} cached)...")

        def one(run_id: str) -> dict[str, Any]:
            result = ask_judge(client, model, prompts[run_id], effort)
            result.update(key=cache_key(model, prompts[run_id]), run_id=run_id, model=model)
            return result

        CACHE.parent.mkdir(parents=True, exist_ok=True)
        with (
            ThreadPoolExecutor(max_workers=workers) as pool,
            CACHE.open("a", encoding="utf-8") as fh,
        ):
            for result in pool.map(one, todo):
                fh.write(json.dumps(result, ensure_ascii=False) + "\n")
                cache[result["key"]] = result
        spent = sum(cache[cache_key(model, prompts[r])]["cost_usd"] for r in todo)
        print(f"Spent ${spent:.2f} on this call.")
    return {rid: cache[cache_key(model, p)] for rid, p in prompts.items()}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("prompt", type=Path, help="judge prompt (Markdown with {{run}})")
    parser.add_argument(
        "traces", nargs="*", help="trace globs (default: three-day/traces/baseline.jsonl)"
    )
    parser.add_argument("--split", choices=["dev", "test", "rest", "all"], default="dev")
    parser.add_argument("--labels", type=Path, default=WORK / "labels.csv", help="your labels")
    parser.add_argument("--mode", help="compare against one failure mode, not the overall label")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"]
    )
    parser.add_argument(
        "--via",
        default="auto",
        choices=["auto", "api", "claude"],
        help="api needs ANTHROPIC_API_KEY; claude uses Claude Code (claude -p). "
        "auto: api if a key is set, else claude",
    )
    parser.add_argument(
        "--tpr", type=float, help="judge TPR measured on labelled data, for correction"
    )
    parser.add_argument(
        "--tnr", type=float, help="judge TNR measured on labelled data, for correction"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print one prompt and a cost estimate"
    )
    args = parser.parse_args()

    template = args.prompt.read_text(encoding="utf-8")
    runs = [
        r
        for r in load_runs(*args.traces)
        if args.split == "all" or split_of(r["run_id"]) == args.split
    ]
    if not runs:
        raise SystemExit(f"No runs in the {args.split} split")

    if args.dry_run:
        example = build_prompt(template, runs[0])
        print(example)
        tokens = sum(len(build_prompt(template, r)) for r in runs) / 4  # ~4 characters a token
        price_in, price_out = PRICES.get(args.model, PRICES[DEFAULT_MODEL])
        estimate = (tokens * price_in + len(runs) * 1500 * price_out) / 1_000_000
        print(
            f"\n--- {len(runs)} runs, about {tokens:,.0f} input tokens: "
            f"roughly ${estimate:.2f} with {args.model}"
        )
        return

    try:
        results = judge_runs(runs, template, model=args.model, effort=args.effort, via=args.via)
    except RuntimeError as exc:  # support_agent.config.MissingCredential
        raise SystemExit(f"{exc}\n(--dry-run works without a key.)") from None
    stem = args.prompt.stem
    out = RESULTS / f"judge-{stem}-{args.split}.csv"
    with out.open("w", encoding="utf-8") as fh:
        fh.write("run_id,split,verdict,critique\n")
        for run_id, r in sorted(results.items()):
            critique = r["critique"].replace('"', "'").replace("\n", " ")
            fh.write(f'{run_id},{split_of(run_id)},{r["verdict"]},"{critique}"\n')

    verdicts = {rid: r["verdict"] == "pass" for rid, r in results.items() if r["verdict"]}
    passes = sum(verdicts.values())
    print(f"\n{stem} on {args.split}: judge pass rate {fmt_rate(passes, len(verdicts))}")
    if len(verdicts) < len(results):
        print(f"  ({len(results) - len(verdicts)} runs got no verdict; see {out})")

    labels = read_labels(args.labels)
    if labels:
        if args.mode:
            # Against one failure mode: the reference "fails" a run only if a
            # person failed it for this reason.
            human = {
                r: not (row["label"] == "fail" and args.mode in tags(row))
                for r, row in labels.items()
            }
        else:
            human = {r: row["label"] == "pass" for r, row in labels.items()}
        a = agreement(verdicts, human)
        print_agreement(a, "judge", "human")
        wrong = sorted(r for r in verdicts if r in human and verdicts[r] != human[r])
        for r in wrong:
            said = "pass" if verdicts[r] else "fail"
            print(f"\n  {r}: judge said {said}, you said {'pass' if human[r] else 'fail'}")
            print(f"    judge: {results[r]['critique'][:400]}")
            print(f"    you:   {labels[r].get('note', '')}")
    else:
        print(
            f"\nNo labels at {args.labels}; label some runs (Day 2) to see how far to trust this."
        )

    if args.tpr is not None and args.tnr is not None:
        observed = passes / len(verdicts) if verdicts else float("nan")
        corrected = corrected_pass_rate(observed, args.tpr, args.tnr)
        if corrected is None:
            print(
                "\nTPR + TNR <= 1: this judge is no better than a coin. "
                "Its pass rate means nothing."
            )
        else:
            print(
                f"\nObserved {observed:.0%}; corrected for the judge's known errors: "
                f"{corrected:.0%}"
            )

    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
