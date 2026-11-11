# Evals in three days

A hands-on path for someone who has never built an eval and has three days to
learn. You score a real agent three ways, find out where each way is blind, and
finish by using your eval to prove that a change made the agent better.

**You will not write code.** A coding agent (Claude Code or similar) writes it
for you. What you learn is the part it cannot do: deciding what correct means,
telling it precisely what to build, and checking that what it built does that.
[`concepts.md`](concepts.md) explains each eval idea in those terms: the idea,
how to ask for it, and how to check you got it. Keep it open throughout.

| Day | You score with | You leave with |
|---|---|---|
| [1. Code graders](day1-code-graders.md) | Checks your coding agent writes from your spec, which cost nothing to run | Five graders, and a pass rate that looks healthy |
| [2. Human review](day2-human-review.md) | Your own eyes, then a second person's | Labels for 25 runs, a list of failure modes, and the discovery that the real pass rate is about half |
| [3. LLM-as-judge](day3-llm-judge.md) | A model grading against a rubric built from your criteria | A judge you have measured against your labels, and a before-and-after on a fix |

Each day is about six hours with breaks. Every exercise ends with a check you can
run, so you know when you are done.

## The one idea

An eval is only as good as the evidence that it agrees with a careful person. So
the order is fixed: **look at the data, write cheap checks, label by hand, and
only then hand the judging to a model, after you have measured how often it
agrees with you.** Most teams skip the middle step. This course is built so that
skipping it visibly fails.

## What you are evaluating

The repository's support agent for a fictional shop, Northwind Goods. It reads a
customer's message, looks up the shop's policies, and can look up orders, issue
refunds and hand over to a person. It is about 900 lines; you do not need to read
it, but [`src/support_agent/agent.py`](../src/support_agent/agent.py) is the place
to start if you want to.

You get 25 recorded runs to start: five customer requests, each run five times.
Running the same request five times is the first lesson. The agent does not do
the same thing every time.

## Setup (20 minutes)

You need [uv](https://docs.astral.sh/uv/) and a coding agent that can edit files
and run commands in this repository. Days 1 and 2 cost nothing to run. Day 3
needs an Anthropic API key and up to about $10 of usage.

Start your coding agent at the repository root and open with:

> I'm doing the three-day evals course in `three-day/`. Read
> `three-day/AGENTS.md` and `three-day/concepts.md`, then run the setup checks in
> `three-day/README.md` and tell me whether they pass.

The setup checks are:

```bash
uv sync
uv run python three-day/lab/grade.py          # should print a table and "24/25"
uv run pytest -q tests/test_three_day.py      # should pass
cp .env.example .env                          # Day 3: put your key in it
```

`three-day/AGENTS.md` keeps your coding agent out of the parts you must do
yourself: it will not label runs for you, open the answer key, or tune a judge on
the runs held back to test it. Claude Code picks it up through `CLAUDE.md`; other
agents read `AGENTS.md`.

All commands run from the repository root. One command, `label.py`, asks you
questions as it goes, so run that one in your own terminal.

## What is in here

```text
three-day/
  concepts.md   each eval idea: what it is, how to ask for it, how to check it
  AGENTS.md     rules for your coding agent
  day1-code-graders.md   day2-human-review.md   day3-llm-judge.md
  cases/        the five requests, each with what a correct run must and must not do
  lab/          the harness, in plain Python; ask your coding agent to explain any part
    graders.py    code graders (your coding agent builds two from your specs)
    grade.py      run the graders over runs, with pass rates and intervals
    label.py      label runs by hand, one at a time
    agree.py      compare two sets of labels
    judge.py      run an LLM judge and measure it against your labels
    compare.py    before vs after a change
  judges/       a deliberately naive starter judge prompt
  work/         your labels, criteria and judges go here
  answer-key/   reference labels, graders and judges: open each only when a day says so
```

## If you have more time

- The full course this repository serves, **Agent Eval Forge**, takes each of these
  days further over several weeks: calibration records, holdout splits, a CI gate,
  red-teaming, and production monitoring. Day 3's last section maps where to go
  next.
- Once you trust an eval, the improvement loop on Day 3 can be automated: generate
  candidate prompt changes, score them on a training split, and keep a winner only
  if it also wins on a split the loop never tuned against.
