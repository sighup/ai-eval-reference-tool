"""Record runs of the support agent against the course database.

    uv run python three-day/lab/record.py --repeat 5 --out three-day/traces/before.jsonl
    uv run python three-day/lab/record.py --case order-status --repeat 1 --out /tmp/x.jsonl

Each run gets a fresh copy of the seed database, so a refund in one run never
shows up in the next. Two files come out:

* ``<out>``: one trace per run, in the reference tool's trace format.
* ``<out stem>.effects.jsonl``: the rows each run wrote to its database
  (refunds, cancellations, escalations). This is what the run *did*, read back
  from the database rather than taken from what the agent said.

Two ways to run the support agent:

``--via claude`` (the default) runs it through Claude Code (``claude -p``), with
the support agent's system prompt in place of Claude Code's and its tools served
by ``mcp_server.py``. No API key is needed: it uses whatever Claude Code is
signed in with. What differs from the API runner: temperature and max_tokens
cannot be set, tool names reach the model as ``mcp__northwind__<name>`` (the trace
records them without the prefix), and Claude Code's loop runs instead of
``support_agent.agent`` (so the model writes a closing message after escalating).

``--via api`` runs ``support_agent.agent`` with the Anthropic API. It needs
``ANTHROPIC_API_KEY``.

Both write the same trace format, so every grader and judge reads either.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import claude_cli
from common import COURSE, ROOT, load_cases

from support_agent import (
    agent,
    config,
    prompts,
    retrieve,
    sqlite_store,
    tools,
    trace,
)

PREFIX = "mcp__northwind__"
DEFAULT_MODEL = "claude-haiku-5-5"
#: Turns allowed per run. Matches the API runner's step cap closely enough.
MAX_TURNS = 10

#: Claude Code always tells the model the real date and its working directory,
#: even with its system prompt replaced, and nothing can switch that off. The
#: support agent's "today" is pinned (config.AS_OF_DATE), so without this line it
#: sees two dates and sometimes counts from the wrong one. The line is appended
#: to the system prompt, and the trace records the prompt as sent, with it.
DATE_NOTE = (
    "\n\nThe date above is the only date that applies. Ignore any other date or "
    "environment detail you are shown; it describes the computer running you, not "
    "this conversation."
)


def effects_path(out: Path) -> Path:
    return out.with_name(out.stem + ".effects.jsonl")


# --------------------------------------------------------------------------- #
# Through Claude Code
# --------------------------------------------------------------------------- #


def claude_command(system_file: Path, mcp_file: Path, model: str, effort: str | None) -> list:
    cmd = claude_cli.base_command(model, system=["--system-prompt-file", str(system_file)])
    cmd += [
        "--tools",
        "",
        "--mcp-config",
        str(mcp_file),
        "--allowedTools",
        f"{PREFIX}*",
        "--max-turns",
        str(MAX_TURNS),
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    if effort:
        cmd += ["--effort", effort]
    return cmd


def run_claude(case: dict, run_id: str, model: str, effort: str | None) -> dict[str, Any]:
    fixture = agent.Fixture.from_dict(case)
    as_of = case.get("as_of", config.AS_OF_DATE)
    directory = tools.reset_run_dir(run_id)
    schemas = tools.tool_schemas()

    system = prompts.render_system(fixture.customer_id, fixture.session_id, as_of) + DATE_NOTE
    retrieved = [hit.to_trace() for hit in retrieve.retrieve(fixture.message)]
    rendered = prompts.render_context(fixture.message, retrieved)

    system_file = directory / "system.txt"
    system_file.write_text(system, encoding="utf-8")
    mcp_file = directory / "mcp.json"
    server = Path(__file__).resolve().parent / "mcp_server.py"
    mcp_file.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "northwind": {
                        "command": sys.executable,
                        "args": [
                            str(server),
                            "--run-id",
                            run_id,
                            "--customer",
                            fixture.customer_id,
                            "--session",
                            fixture.session_id,
                            "--as-of",
                            as_of,
                        ],
                        "env": {"SUPPORT_AGENT_BACKEND": "sqlite"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    # An empty directory and a stripped environment: the support agent sees its
    # own prompt and nothing of Claude Code's (see claude_cli.py).
    proc = claude_cli.run(claude_command(system_file, mcp_file, model, effort), rendered)
    (directory / "claude.jsonl").write_text(proc.stdout, encoding="utf-8")
    events = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    if not any(e.get("type") == "result" for e in events):
        raise RuntimeError(f"{run_id}: claude -p gave no result.\n{proc.stderr[-2000:]}")

    return to_trace(events, fixture, run_id, as_of, system, schemas, retrieved, rendered, effort)


def to_trace(
    events: list[dict],
    fixture: agent.Fixture,
    run_id: str,
    as_of: str,
    system: str,
    schemas: list[dict],
    retrieved: list[dict],
    rendered: str,
    effort: str | None,
) -> dict[str, Any]:
    """Turn Claude Code's stream-json events into a trace-v1 run."""
    init = next(e for e in events if e.get("type") == "system" and e.get("subtype") == "init")
    result = next(e for e in events if e.get("type") == "result")

    # One assistant message can arrive as several events (one per content block),
    # all sharing a message id. Merge them back into turns, in order.
    turns: list[dict[str, Any]] = []
    tool_results: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("type") == "assistant":
            message = event["message"]
            if not turns or turns[-1]["id"] != message["id"]:
                turns.append({"id": message["id"], "text": [], "calls": []})
            for block in message.get("content", []):
                if block.get("type") == "text" and block.get("text", "").strip():
                    turns[-1]["text"].append(block["text"])
                elif block.get("type") == "tool_use":
                    turns[-1]["calls"].append(block)
        elif event.get("type") == "user":
            for block in event["message"].get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool_results[block["tool_use_id"]] = block

    builder = trace.TraceBuilder(
        run_id=run_id,
        fixture_id=fixture.fixture_id,
        mode="live",
        model=init.get("model", "unknown"),
        params={
            # Not settable through Claude Code; these are the API defaults it uses.
            "max_tokens": config.MAX_TOKENS,
            "temperature": config.TEMPERATURE,
            "runner": "claude-code",
            "claude_code_version": init.get("claude_code_version"),
            "effort": effort,
        },
        customer_id=fixture.customer_id,
        session_id=fixture.session_id,
        message=fixture.message,
        system_prompt=system,
        tool_schemas=schemas,
        fingerprint=prompts.fingerprint(schemas),
    )
    builder.add_user_step(fixture.message, rendered, retrieved=retrieved)

    counter = 0
    escalated = False
    final_output = ""
    for turn in turns:
        text = "\n\n".join(turn["text"])
        if text:
            final_output = text
        if not turn["calls"]:
            builder.add_agent_step(text)
            continue
        calls, observations = [], []
        for block in turn["calls"]:
            counter += 1
            call_id = f"tc-{counter}"
            name = block["name"].removeprefix(PREFIX)
            escalated = escalated or name in tools.TERMINAL_TOOLS
            calls.append({"tool_call_id": call_id, "name": name, "arguments": block["input"]})
            observations.append(_observation(call_id, tool_results.get(block["id"])))
        builder.add_agent_step(text, tool_calls=calls)
        builder.add_system_step(observations)

    usage = result.get("usage", {})
    builder.add_usage(
        int(usage.get("input_tokens", 0)) + int(usage.get("cache_creation_input_tokens", 0)),
        int(usage.get("output_tokens", 0)),
        int(usage.get("cache_read_input_tokens", 0)),
    )

    if result.get("subtype") == "error_max_turns":
        stop = "max_steps"
    elif escalated:
        stop = "escalated"
    elif result.get("stop_reason") in {"end_turn", "max_tokens", "stop_sequence", "refusal"}:
        stop = result["stop_reason"]
    else:
        stop = "end_turn"
    built = builder.build(final_output, stop)
    built["cost_usd"] = round(float(result.get("total_cost_usd") or 0.0), config.COST_PRECISION)
    return built


def _observation(call_id: str, block: dict | None) -> dict[str, Any]:
    if block is None:
        content: Any = {"error": "no_result", "message": "The tool returned nothing."}
        return {"source_call_id": call_id, "content": content, "is_error": True}
    raw = block.get("content")
    if isinstance(raw, list):
        raw = "".join(part.get("text", "") for part in raw if isinstance(part, dict))
    try:
        content = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        content = {"text": raw}
    if not isinstance(content, dict):
        content = {"value": content}
    return {"source_call_id": call_id, "content": content, "is_error": bool(block.get("is_error"))}


# --------------------------------------------------------------------------- #
# Through the API
# --------------------------------------------------------------------------- #


def run_api(case: dict, run_id: str, model: str, effort: str | None) -> dict[str, Any]:
    from support_agent.model import LiveProvider

    fixture = agent.Fixture.from_dict(case)
    provider = LiveProvider(
        model=model, max_tokens=config.MAX_TOKENS, temperature=config.TEMPERATURE
    )
    return agent.run(fixture, provider, run_id=run_id, as_of=case.get("as_of", config.AS_OF_DATE))


# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--case", action="append", help="fixture id (repeatable); default all")
    parser.add_argument(
        "--cases",
        choices=["all", "climb", "holdout"],
        default="all",
        help="climb: the cases you hill-climb on; holdout: the ones you check once at the end",
    )
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--via", choices=["claude", "api"], default="claude")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--start", type=int, default=1, help="first repeat number")
    args = parser.parse_args(argv)
    # The course always runs against its database, whichever runner is used.
    os.environ["SUPPORT_AGENT_BACKEND"] = "sqlite"
    # The course's own copy of the prompts and policy corpus: the ones you tune.
    os.environ.setdefault("SUPPORT_AGENT_DIR", str(COURSE / "agent"))

    cases = load_cases()
    chosen = args.case or sorted(
        c
        for c in cases
        if args.cases == "all" or cases[c]["metadata"].get("climb_split") == args.cases
    )
    unknown = [c for c in chosen if c not in cases]
    if unknown:
        raise SystemExit(f"unknown case(s): {', '.join(unknown)}")

    out = args.out if args.out.is_absolute() else ROOT / args.out
    jobs = [
        (cases[c], trace.run_id_for(c, i))
        for c in chosen
        for i in range(args.start, args.start + args.repeat)
    ]
    runner = run_claude if args.via == "claude" else run_api
    print(f"recording {len(jobs)} run(s) via {args.via} ({args.model}) -> {out}")

    def one(job: tuple[dict, str]) -> tuple[dict | None, dict, str]:
        case, run_id = job
        try:
            built = runner(case, run_id, args.model, args.effort)
        except Exception as exc:  # report and carry on with the other runs
            return None, {}, f"{run_id}: {type(exc).__name__}: {exc}"
        fx = sqlite_store.effects(tools.run_dir(run_id), run_id)
        return built, {"run_id": run_id, **fx}, ""

    done, failed, cost = [], [], 0.0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for built, fx, error in pool.map(one, jobs):
            if built is None:
                failed.append(error)
                print(f"  FAILED {error}")
                continue
            done.append((built, fx))
            cost += built["cost_usd"]
            print(
                f"  {built['run_id']:<40} {built['stop_reason']:<10} "
                f"{len(built['steps']):>2} steps  ${built['cost_usd']:.4f}"
            )

    for built, fx in sorted(done, key=lambda pair: pair[0]["run_id"]):
        trace.write(built, out)
        with effects_path(out).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(fx, ensure_ascii=False) + "\n")

    print(f"\n{len(done)} run(s) written, {len(failed)} failed, ${cost:.4f}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
