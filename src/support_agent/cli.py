"""The command line: ``run``, ``validate``, ``diff``.

Three subcommands, and the boundary between them and everything a learner builds
is deliberate.

``run`` produces one trace per run. ``diff`` compares **two** of them. Neither
aggregates: there is no command that takes twenty runs and reports a pass rate, a
score, or a verdict, because deciding what to measure and how to summarise it is
the harness — and the harness is the thing being learned. A tool that shipped a
``score`` subcommand would answer the question the course is asking.

Live is the default mode. ``--replay PATH`` serves turns from a recording instead,
which costs nothing and holds the model still, but cannot notice a prompt edit.
See :mod:`support_agent.replay` for what that is good for.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from . import __version__, agent, config, prompts, replay, trace
from .model import LiveProvider, Provider

#: Errors a user can cause. Reported as one line, not a traceback: a missing key
#: or a typo in a fixture path is not a bug in the tool. ``ValueError`` is on the
#: list because the argument checks below raise it directly, and because most of
#: the named errors above are subclasses of it anyway.
EXPECTED_ERRORS = (
    agent.FixtureError,
    config.MissingCredential,
    prompts.UnrenderedPlaceholder,
    replay.ReplayExhausted,
    trace.TraceValidationError,
    FileNotFoundError,
    ValueError,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="support-agent",
        description="Run the support agent against a fixture and emit an evaluable trace.",
    )
    parser.add_argument("--version", action="version", version=f"support-agent {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser(
        "run",
        help="Run one fixture and append its trace to a JSONL file.",
        description=(
            "Calls the API by default. Pass --replay to serve turns from a recording "
            "instead, which costs nothing but cannot respond to a prompt edit."
        ),
    )
    run.add_argument("--fixture", required=True, type=Path, help="Path to a fixture JSON file.")
    run.add_argument(
        "--replay",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Serve model turns from a recorded trace file instead of calling the API. "
            "No key needed and no HTTP client is constructed."
        ),
    )
    run.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Run the fixture N times, accumulating into one trace file. One sample "
            "cannot tell a reliable behaviour from an occasional one."
        ),
    )
    run.add_argument("--model", default=config.DEFAULT_MODEL, metavar="M")
    run.add_argument("--temperature", type=float, default=config.TEMPERATURE, metavar="T")
    run.add_argument(
        "--max-steps",
        type=int,
        default=config.DEFAULT_MAX_STEPS,
        metavar="N",
        help="Model turns before the run stops with stop_reason 'max_steps'.",
    )
    run.add_argument(
        "--as-of",
        default=config.AS_OF_DATE,
        metavar="DATE",
        help=(
            "The agent's notion of today. Pinned by default so a run means the same "
            "thing on any day; changing it changes the prompt."
        ),
    )
    run.add_argument(
        "--trace-out",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Append traces here. Defaults to traces/<fixture_id>.jsonl. Two paths is "
            "how you get a before and an after."
        ),
    )
    run.add_argument(
        "--run-id",
        default=None,
        metavar="ID",
        help="Override the derived run id. Only valid with --repeat 1.",
    )

    validate = sub.add_parser(
        "validate",
        help="Check trace files against schema/trace-v1.json.",
        description=(
            "Validates every run in every file given. Use it on traces you have "
            "edited or generated yourself, before a scorer depends on their shape."
        ),
    )
    validate.add_argument("paths", nargs="+", type=Path, metavar="PATH")

    diff = sub.add_parser(
        "diff",
        help="Compare two runs on behaviour.",
        description=(
            "Reports what the agent did differently: which configuration produced the "
            "run, which tools it called with which arguments, what retrieval fed it, "
            "why it stopped, and whether the answer text changed at all. Token counts, "
            "cost, the clock and the run id are normalised out. Whether a changed "
            "answer is better is a question for a scorer, and this does not answer it."
        ),
    )
    diff.add_argument("before", type=Path)
    diff.add_argument("after", type=Path)
    diff.add_argument(
        "--fixture-id",
        default=None,
        help="Compare this fixture's runs when a file holds more than one fixture.",
    )

    return parser


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #


def _provider(args: argparse.Namespace, fixture: agent.Fixture) -> Provider:
    if args.replay is not None:
        return replay.ReplayProvider.from_file(args.replay, fixture_id=fixture.fixture_id)
    return LiveProvider(
        model=args.model, max_tokens=config.MAX_TOKENS, temperature=args.temperature
    )


def cmd_run(args: argparse.Namespace) -> int:
    fixture = agent.Fixture.from_file(args.fixture)

    if args.repeat < 1:
        raise ValueError(f"--repeat must be at least 1, got {args.repeat}")
    if args.run_id and args.repeat > 1:
        raise ValueError(
            "--run-id names one run, but --repeat asks for several. Each run needs its "
            "own id or they share a runs/<run_id>/ directory and overwrite each other's "
            "side effects. Drop --run-id, or use --repeat 1."
        )

    trace_out = args.trace_out or config.traces_dir() / f"{fixture.fixture_id}.jsonl"

    mode = "replay" if args.replay is not None else "live"
    print(f"fixture {fixture.fixture_id}  ({fixture.customer_id}, {mode})")
    if mode == "live":
        print(f"model {args.model}  temperature {args.temperature}  as of {args.as_of}")
    print()

    total_cost = 0.0
    written: list[dict[str, Any]] = []
    for index in range(1, args.repeat + 1):
        run_id = args.run_id or trace.run_id_for(fixture.fixture_id, index)
        result = agent.run(
            fixture,
            _provider(args, fixture),
            run_id=run_id,
            as_of=args.as_of,
            max_steps=args.max_steps,
        )
        trace.write(result, trace_out)
        written.append(result)
        total_cost += result["cost_usd"]
        print(
            f"  {run_id}  {result['stop_reason']:<12} "
            f"{len(result['steps']):>2} steps  ${result['cost_usd']:.6f}"
        )

    print(f"\n{len(written)} run(s) appended to {_display(trace_out)}")
    print(f"total cost ${total_cost:.6f}")

    if len(written) == 1:
        print(f"\n--- final_output ---\n{written[0]['final_output']}")

    return 0


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #


def cmd_validate(args: argparse.Namespace) -> int:
    failures = 0
    total = 0
    for path in args.paths:
        if not path.is_file():
            print(f"{_display(path)}: not a file")
            failures += 1
            continue
        runs = trace.read(path)
        bad = 0
        for lineno, run in enumerate(runs, start=1):
            total += 1
            try:
                trace.validate(run)
            except trace.TraceValidationError as exc:
                bad += 1
                print(f"{_display(path)}:{lineno} ({run.get('run_id', '?')})\n{exc}")
        failures += bad
        if not bad:
            print(f"{_display(path)}: {len(runs)} run(s) valid")

    print(f"\n{total - failures}/{total} run(s) valid against {_display(config.schema_path())}")
    return 1 if failures else 0


# --------------------------------------------------------------------------- #
# diff
# --------------------------------------------------------------------------- #


def cmd_diff(args: argparse.Namespace) -> int:
    left = _pick(args.before, args.fixture_id)
    right = _pick(args.after, args.fixture_id)

    print(f"before  {left['run_id']}  {_display(args.before)}")
    print(f"after   {right['run_id']}  {_display(args.after)}")
    print()

    lines = trace.diff(left, right)
    if not lines:
        print("no behavioural difference")
        print(f"(normalised out: {', '.join(trace.VOLATILE_FIELDS)})")
    else:
        for line in lines:
            print(line)

    # Always 0. An exit code would read as a verdict, and deciding whether a
    # difference is an improvement is the harness's job, not this command's.
    return 0


def _pick(path: Path, fixture_id: str | None) -> dict[str, Any]:
    """The run to compare from ``path``: the last one, or the last for a fixture.

    The last rather than the first, because a trace file grows by appending and
    the most recent run is the one you just made.
    """
    runs = trace.read(path)
    if not runs:
        raise ValueError(f"{path} holds no runs")
    if fixture_id is not None:
        runs = [run for run in runs if run.get("fixture_id") == fixture_id]
        if not runs:
            raise ValueError(f"{path} holds no runs for fixture {fixture_id!r}")
    else:
        fixtures = {str(run.get("fixture_id")) for run in runs}
        if len(fixtures) > 1:
            print(
                f"note: {_display(path)} holds runs for {len(fixtures)} fixtures "
                f"({', '.join(sorted(fixtures))}); comparing the last one. "
                "Pass --fixture-id to choose."
            )
    return runs[-1]


# --------------------------------------------------------------------------- #


def _display(path: Path) -> str:
    """A path relative to the project root when it is inside it, else absolute."""
    try:
        return str(path.resolve().relative_to(config.project_root()))
    except ValueError:
        return str(path)


COMMANDS = {"run": cmd_run, "validate": cmd_validate, "diff": cmd_diff}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except EXPECTED_ERRORS as exc:
        print(f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
