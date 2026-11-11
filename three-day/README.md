# Evals in three days

A hands-on path for someone who has never built an eval and has three days to
learn. You score a real agent three ways, find out where each way is blind, and
finish by using your eval to make the agent better, one measured change at a
time, without fooling yourself.

**You will not write code.** A coding agent (Claude Code or similar) writes it
for you. What you learn is the part it cannot do: deciding what correct means,
telling it precisely what to build, and checking that what it built does that.
[`concepts.md`](concepts.md) explains each eval idea in those terms: the idea,
how to ask for it, and how to check you got it. Keep it open throughout.

| Day | You score with | You leave with |
|---|---|---|
| [1. Code graders](day1-code-graders.md) | Checks your coding agent writes from your spec, which cost nothing to run | Six graders, including one for retrieval, and a pass rate that looks healthy |
| [2. Human review](day2-human-review.md) | Your own eyes, then a second person's | Labels for 38 runs, a list of failure modes, and the discovery that the graders pass about as many runs as you do, but not the same ones |
| [3. Judge and climb](day3-llm-judge.md) | A model grading against your rubric, then the whole eval as one score | A grounding judge measured against your labels, and a hill-climb that raised the score, checked on cases it never saw |

Each day is about six hours with breaks. Every exercise ends with a check you can
run, so you know when you are done.

## The one idea

An eval is only as good as the evidence that it agrees with a careful person. So
the order is fixed: **look at the data, write cheap checks, label by hand, and
only then hand the judging to a model, after you have measured how often it
agrees with you.** Most teams skip the middle step. This course is built so that
skipping it visibly fails. The last step, climbing a score, only works because
of the others: a loop that optimises an unmeasured score gets very good at
pleasing it.

## What you are evaluating

The repository's support agent for a fictional shop, Northwind Goods. It reads a
customer's message, is handed the shop policies that best match it, and has
tools to look up orders, find a customer's orders, issue refunds, cancel orders
and hand over to a person. The tools read and write a small SQLite database of
customers, orders, shipments, returns and refunds, with the mess a real shop's
data has: a customer who moved, a split shipment, a delivery with no date, a
payment provider that fails. Every run gets its own fresh copy, so what one run
does never leaks into the next.

You get 190 recorded runs to start: 38 customer requests, each run five times.
Running the same request five times is the first lesson. The agent does not do
the same thing every time.

## Setup (20 minutes)

You need [uv](https://docs.astral.sh/uv/) and a coding agent that can edit files
and run commands in this repository. Days 1 and 2 cost nothing to run. Day 3
runs the judge and records new runs, which needs either an Anthropic API key or
a signed-in [Claude Code](https://claude.com/claude-code); budget up to about $10
of usage.

Start your coding agent at the repository root and open with:

> I'm doing the three-day evals course in `three-day/`. Read
> `three-day/AGENTS.md` and `three-day/concepts.md`, then run the setup checks in
> `three-day/README.md` and tell me whether they pass.

The setup checks are:

```bash
uv sync
uv run python three-day/db/seed.py            # builds the shop database
uv run python three-day/lab/grade.py          # should end with "ALL RUNS  175/190"
uv run pytest -q tests/test_three_day.py tests/test_three_day_backends.py
cp .env.example .env                          # Day 3, if you use an API key
```

`three-day/AGENTS.md` keeps your coding agent out of the parts you must do
yourself: it will not label runs for you, open the answer key, or tune anything
on the runs held back to test it. Claude Code picks it up through `CLAUDE.md`;
other agents read `AGENTS.md`.

All commands run from the repository root. One command, `label.py`, asks you
questions as it goes, so run that one in your own terminal.

## What is in here

```text
three-day/
  concepts.md   each eval idea: what it is, how to ask for it, how to check it
  AGENTS.md     rules for your coding agent
  day1-code-graders.md   day2-human-review.md   day3-llm-judge.md
  cases/        38 requests, each with what a correct run must and must not do
  db/seed.py    builds the shop's SQLite database the tools read and write
  agent/        the support agent's prompt and policy documents: Day 3 changes them
  traces/       the 190 recorded runs, and what each one wrote to its database
  lab/          the harness, in plain Python; ask your coding agent to explain any part
    graders.py    code graders (your coding agent builds four from your specs)
    grade.py      run the graders over runs, with pass rates and intervals
    label.py      label runs by hand, one at a time
    agree.py      compare two sets of labels
    judge.py      run an LLM judge and measure it against your labels
    record.py     record new runs of the support agent
    score.py      one score for a set of runs, logged, for hill-climbing
  judges/       a deliberately naive starter judge prompt
  work/         your labels, criteria and judges go here
  answer-key/   reference labels, graders and judges: open each only when a day says so
```

## If you have more time

- The full course this repository serves, **Agent Eval Forge**, takes each of these
  days further over several weeks: calibration records, a CI gate, red-teaming,
  and production monitoring. Day 3's last section maps where to go next.
- Day 3's climb can be handed to a loop that proposes and scores changes on its
  own, such as the autoresearch plugin for Claude Code. `score.py` prints a last
  line of `SCORE <number>` for that reason. Hand it over only once you trust the
  score, and keep the holdout check for yourself.
- The cases are all one message long. Real support is a conversation, and
  multi-turn cases are the natural next step.
