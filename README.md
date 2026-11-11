# The reference tool

A retrieval-augmented customer-support agent for a fictional online retailer,
Northwind Goods. It reads a customer's message, retrieves policy documents from a
local knowledge base, and may act on the customer's order through three tools.

It is not the thing you are building. **You are building the eval harness; this is
the thing your harness measures.** It exists so you do not have to bring your own
application, and so that everyone in the room is scoring the same system and can
compare notes.

It has weaknesses. Some of them you will find by evaluating it, and then you will
fix them — by editing the system prompt, the tool definitions, or the knowledge
base — and measure whether your fix worked. That loop is the course.

The whole tool is about 900 lines and is meant to be read end to end in twenty
minutes or so. Start with `src/support_agent/agent.py`; it is the only file that
decides what happens next.

## New to evals? Start with the three-day path

[`three-day/`](three-day/README.md) is a self-contained, hands-on route through
the essentials in three days: code graders on Day 1, human review on Day 2, and
an LLM judge measured against your own labels on Day 3. It ships a small harness
around this tool, so it does score runs for you; the full course has you build
that harness yourself.

## Check your progress

Run **Actions → Check your progress** in this repo (or your fork) to score the current
checkout against the chapter registry. Pick one chapter or **all chapters** for a
full scorecard. It is deterministic (files, shapes, counts), never blocks merges, and
never certifies — see [`.github/completion/README.md`](.github/completion/README.md).

## Setup

You need [uv](https://docs.astral.sh/uv/) and an Anthropic API key. The key comes
first, because a live model call is the default mode.

```bash
cp .env.example .env          # then put your key in it
uv sync
uv run support-agent --version
```

Confirm the install without spending anything, by replaying a recording:

```bash
uv run support-agent run --fixture fixtures/starter/001.json \
    --replay traces/starter/refund-outside-window.jsonl
uv run support-agent validate traces/refund-outside-window.jsonl
```

That writes a trace to `traces/refund-outside-window.jsonl` and prints the
agent's answer. If both commands exit 0 you are set up.

### What it costs

Measured, not estimated — these are the figures from recording the starter pack.
Every run prints its own cost and the total for the command, so nothing is a
surprise.

| Command | Runs | Cost |
|---|---|---|
| One fixture, once | 1 | $0.02–0.03 |
| One fixture, `--repeat 5` | 5 | $0.10–0.15 |
| All five fixtures, `--repeat 5` | 25 | ~$0.60 |
| A before/after comparison on one fixture, 5 runs each | 10 | ~$0.25 |

Most of that is input tokens: three full policy documents and the tool definitions
go in on every turn. Judging traces with a model costs more than producing them, so
budget for the judge rather than for this.

## The fixtures

A fixture is an *input* — a customer, a session, and a message. The prompt is
re-rendered from it at run time, so editing a prompt template changes the next
run without the fixtures being touched.

`support-agent run` requires the four flat fields `fixture_id`, `customer_id`,
`session_id`, and `message`. It selects those fields and ignores additional keys,
so a course harness fixture may add top-level `expected` and `metadata` and pass
the same JSON file directly to this command.

```bash
ls fixtures/starter/
```

| Fixture | Asks about |
|---|---|
| `001.json` | A refund on an order placed 87 days ago |
| `002.json` | Where an order is, four days past its delivery estimate |
| `003.json` | Whether an order was delivered, and to what address |
| `004.json` | A duffel bag whose seam split after five months |
| `005.json` | A return, five days after delivery |

`traces/starter/` holds five recorded runs of each, made live and shipped
**unlabelled** — deciding what to call each one is the exercise, not something the
tool hands you.

## The loop the course is about

Run the agent, change one thing, run it again, and compare. Two `--trace-out`
paths is all it takes.

```bash
# Before: five runs of one fixture, into one file.
uv run support-agent run --fixture fixtures/starter/001.json --repeat 5 \
    --trace-out traces/before.jsonl

# Change exactly one thing. The prompts are Markdown; edit them like prose.
$EDITOR prompts/system.md

# After: five more runs, into a different file.
uv run support-agent run --fixture fixtures/starter/001.json --repeat 5 \
    --trace-out traces/after.jsonl

# What moved?
uv run support-agent diff traces/before.jsonl traces/after.jsonl
```

`diff` reports what the agent *did* differently: which of the three editable
surfaces changed, which tools it called with which arguments, what retrieval fed
it, why it stopped, and whether the answer changed at all. It says nothing about
token counts, cost, timestamps, or the fact that the model phrased the same
decision in different words — because two runs of one unchanged prompt differ in
all of those, every time.

**Five runs, not one.** The model does not make the same choice every time. A
weakness that shows up in three runs out of ten is invisible to a single sample,
and telling a reliable behaviour from an occasional one is most of what an eval
harness is for. `diff` compares two runs; deciding what twenty runs *mean* is your
harness's job, and this tool deliberately will not do it for you.

## What you can change

Three surfaces, and the trace records a digest of each so a result can be
attributed to the right one.

| Surface | Files | What it controls |
|---|---|---|
| Prompts | `prompts/system.md`, `prompts/context.md` | What the agent is told to do, and how retrieved documents reach it |
| Tools | `src/support_agent/tools.py` | What the agent is able to do, and what it is allowed to do it to |
| Corpus | `corpus/*.md` | The policies the agent answers from |

Everything else — retrieval, the loop, the trace writer — you are welcome to read
and welcome to change, but a change there changes what your measurements mean.

## Traces

One JSON object per run, one run per line of JSONL. A trace is self-contained: the
rendered system prompt, the tool definitions as sent, the retrieval result, and the
content the model actually received are all in it. Scoring a run needs the trace
and nothing else — which matters, because by the time you are comparing last
Tuesday's runs against today's, the working tree that produced them is gone.

```python
import json
from pathlib import Path

for line in Path("traces/before.jsonl").read_text().splitlines():
    run = json.loads(line)
    print(run["run_id"], run["stop_reason"], len(run["steps"]))
```

`schema/trace-v1.json` is the contract, and every trace is validated against it at
write time. `labels` is an empty object that this tool never writes to; it is there
for you to put your own annotations in.

Two things to know before you write a scorer:

- **`AS_OF_DATE` is pinned** in `src/support_agent/config.py`. The agent's notion
  of today does not move, so "87 days ago" means the same thing on any machine on
  any day, and a changed output means the model changed its mind rather than the
  inputs having drifted.
- **`usage`, `cost_usd`, `timestamp`, `run_id` and `mode` are volatile.**
  `trace.VOLATILE_FIELDS` names them. `fingerprint` and `params` deliberately are
  not: they are what you changed.

## Replay

`--replay PATH` serves the model turns from a recorded trace instead of calling the
API. It costs nothing and it is deterministic, and it has one real limitation you
should know up front:

**Replay cannot notice a prompt edit.** It hands back the recorded turns and
discards the prompt it was given. Edit `prompts/system.md`, replay, and you get the
same trace as before. To find out what an edit did, run live.

What replay is genuinely good for:

1. **Verifying a fix with the model held still.** Add a required parameter to a
   tool, replay the recording of a run where the agent did something you did not
   want, and the recorded call now fails schema validation — proving your change
   blocks that exact behaviour, for free. Then run live to check the model uses the
   new parameter correctly.
2. **Reproducible side effects.** A scorer that reads
   `runs/<run_id>/refund_ledger.jsonl` needs a run that writes one every time.
3. **A fixed target while you develop a judge.** A live run is a moving target: the
   judge disagrees with its previous verdict and you cannot tell whether the judge
   changed or the agent did. Replay removes one of those variables.

Running past the end of a recording is a hard error, never a fall-through to the
API.

## Commands

```bash
support-agent run --fixture PATH        # live by default
    [--replay PATH] [--repeat N] [--model M] [--temperature T]
    [--max-steps N] [--as-of DATE] [--trace-out PATH] [--run-id ID]
support-agent validate PATH...
support-agent diff BEFORE AFTER [--fixture-id ID]
support-agent --version
```

`--trace-out` defaults to `traces/<fixture_id>.jsonl` and always appends, so
`--repeat` accumulates a set in one file.

## Layout

```text
prompts/            system.md and context.md — the templates, editable as prose
corpus/             the knowledge base, one Markdown document per policy
data/               50 customers and 300 orders, committed and hand-maintained
fixtures/starter/   five minimal fixture inputs
traces/starter/     frozen recordings, unlabelled
schema/             trace-v1.json, the contract
src/support_agent/
  agent.py          the loop — start here
  cli.py            run, validate, diff
  model.py          the provider contract and the live API call
  replay.py         the recorded-turn provider
  retrieve.py       BM25 over the corpus
  tools.py          three tool schemas and their bodies
  prompts.py        template loading, rendering, fingerprints
  trace.py          the trace writer, validator, and diff
  config.py         paths, pinned constants, pricing
tests/              our tests, not yours
```

`runs/` and `traces/` are generated and git-ignored, except the frozen recordings
under `traces/starter/`.

## Checks

```bash
uv run ruff check .
uv run pytest -q
```

No CI is configured here. Wiring up your own is coursework.

The suite is small on purpose: unit tests for the deterministic parts — retrieval,
template rendering, the trace contract, tool dispatch, the SDK adapter — plus a
few that run a whole pipeline end to end. It is a baseline that the tool still
works, not a model evaluation. Characterising what this agent actually does is the
thing you are here to build, and a shipped suite that did it for you would answer
the question the course is asking.

Editing the prompt templates never turns the suite red. Changing a tool, the
corpus, or the trace shape turns the recording tests red on purpose: the frozen
traces under `traces/starter/` and `tests/data/` no longer describe what the tool
does now. Replay the stale recordings first if you want to watch your change block
the old behaviour (see Replay above), then re-record them live and commit the new
recordings with the change.

## Safety

Nothing here reaches a network except `api.anthropic.com`, and only on a live run.
`issue_refund` appends a line to a local JSONL file. `escalate_to_human` appends a
line to another one. There is no payment provider, no ticketing system, no email,
no shell, and no code execution. Every side effect lands under `runs/<run_id>/`,
which is cleared at the start of each run so a ledger describes exactly one run.

Every customer, order and address in `data/` is invented, and `example.com` is
reserved by RFC 2606.
