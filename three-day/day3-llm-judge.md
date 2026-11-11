# Day 3 — Judge and climb

**By the end of today** you have a model checking that the agent's replies stick
to its sources, you know how often it agrees with you on runs it was never tuned
on, and you have used the whole eval to make the agent better: one change at a
time, each one scored, and the result checked on cases the climb never saw.

You need either an API key in `.env` or a signed-in Claude Code today. Budget
about $10; the commands print what each call cost. Every judge verdict is cached,
so re-running an unchanged judge is free.

| Time | Block |
|---|---|
| 0:00 | Exercise 3.1: label the test runs (75 min) |
| 1:15 | How a judge goes wrong (15 min) |
| 1:30 | Exercise 3.2: the naive judge (30 min) |
| 2:00 | Break |
| 2:30 | Exercise 3.3: a grounding judge (75 min) |
| 3:45 | Exercise 3.4: the test split, once (15 min) |
| 4:00 | Exercise 3.5: climb (90 min) |
| 5:30 | Exercise 3.6: the holdout, once (20 min) |
| 5:50 | Where to go next (10 min) |

## Exercise 3.1 — label the test runs

Yesterday you labelled run 01 of every case: the **dev** split, which you may
look at as often as you like while you build things. Today you label run 02:
the **test** split, which you will use exactly once, to measure the judge you are
about to build ([concept 9](concepts.md#9-dev-and-test-split)). Label it now,
before the judge exists, so nothing about the judge can colour your labels.

```bash
uv run python three-day/lab/label.py --split test
```

Use the criteria you wrote yesterday. If a run fits none of your failure modes,
that is worth knowing: add a note, and decide later whether it is a new mode.
Commit the file when the tool says 38 labelled.

## How a judge goes wrong

A judge is a model with a rubric. It is cheap, it reads everything, and it can
check qualities code cannot. It also fails in quiet ways: it is lenient, it is
persuaded by confident prose, it checks the question you asked rather than the
one you meant, and it can be fooled by the very text it is grading. You do not
find out which of these your judge does by reading its prompt. You find out by
measuring it against labels you trust.

The rules this course follows:

- **One judge per failure mode, pass or fail.** "Is this good?" is several
  questions. A judge for `wrong_fact` asks one.
- **Critique first, verdict second.** `judge.py` makes the model write its
  reasoning before it commits. You will read those critiques whenever it
  disagrees with you.
- **Tune on dev, report on test.** A judge tuned until it agrees with you on the
  runs you tuned it on proves nothing.
- **Report TPR and TNR, not accuracy.** A judge that passes everything agrees
  with you every time the agent was right.

Read concepts [8](concepts.md#8-llm-judge), [9](concepts.md#9-dev-and-test-split)
and [10](concepts.md#10-calibration-and-the-corrected-pass-rate) before you
start: an agent told to "make the judge agree with my labels" will do exactly
that, using every run it can see, including the ones you meant to hold back.

## Exercise 3.2 — the naive judge

[`judges/naive.md`](judges/naive.md) is the judge most people write first: "was
this a good response?" See exactly what it sends, and what it will cost:

```bash
uv run python three-day/lab/judge.py three-day/judges/naive.md --dry-run
```

Before you run it, write down a prediction: of the dev runs you failed, how many
will this judge also fail? Then run it on dev:

```bash
uv run python three-day/lab/judge.py three-day/judges/naive.md --split dev
```

It prints the judge's pass rate, its agreement with your labels, and every run
where it disagreed with you, with its critique next to your note. Read each one.
Was the judge wrong, or were you? Was the problem that it did not know your
criteria, or that it knew and did not check?

`judge.py` uses the API when `ANTHROPIC_API_KEY` is set and Claude Code
otherwise; add `--via claude` or `--via api` to choose.

## Exercise 3.3 — a grounding judge

Yesterday's code grader asked whether the agent was *given* the right policy.
The other half of grounding ([concept 12](concepts.md#12-grounding-retrieval-and-faithfulness))
is whether it *stuck to* its sources: does every fact in the reply come from a
tool result, a policy excerpt, or what the customer said? A reply that tells a
customer their own order is not on their account, or invents a delivery date,
fails this, and there is no tool call to catch it with. Code would need a
pattern for every way of saying it. This is a judge's job.

If you followed the course, your `criteria.md` has a mode like `wrong_fact` for
this. A rubric that works usually has:

1. **One question**, stated first, with the failure mode's name.
2. **The sources of truth**: what the judge should treat as correct (tool
   results, including whose order it is; the policy excerpts; today's date; who is
   signed in) and what it should not trust (the agent's own claims).
3. **How to check**: the steps you took when you caught this failure. List every
   factual claim in the reply, then find each one in the sources.
4. **Pass and fail, defined.** Copy from `criteria.md`.
5. **What is out of scope.** Tell it what *not* to fail for: tone, length, and
   whether the right policy was retrieved, which your code grader already checks.
   Otherwise it fails runs for everything else it notices.
6. `{{run}}` where the run goes.

Ask your coding agent for exactly that, built from your `criteria.md`:

> Draft a judge prompt at `three-day/work/judges/grounded.md` for the
> `wrong_fact` failure mode in my `criteria.md`: every fact the reply states must
> be supported by the tool results, the policy excerpts or the customer's own
> message. Structure: the one question; the sources of truth; the steps to
> check; pass and fail defined from my criteria; what is out of scope; `{{run}}`
> at the end. Use no facts from any particular run. Show me the prompt before
> running it.

Read it before it runs. Then have it run against just that failure mode:

```bash
uv run python three-day/lab/judge.py three-day/work/judges/grounded.md \
    --split dev --mode wrong_fact
```

With `--mode`, a run counts as a reference fail only if you failed it with that
tag. Now iterate, and keep the agent on a short lead:

> For each disagreement on the dev split, show me the judge's critique and my
> note side by side, and propose one general change to the rubric. Don't apply
> it yet, and don't run the test split.

Accept a change only if it would hold on runs you have not seen. The tell of a
bad one is a fact from a particular run in the rubric ("order B-5414 belongs to
the customer"): that is the judge learning the answers, and it will not survive
the test split. Agents reach for this fix because it works on the runs in front
of them, so read every edit.

**Done when** the judge agrees with you on every dev run, or you can explain each
remaining disagreement. Be honest about the numbers: the dev split may hold only
one or two runs that fail for this mode. Agreeing on one failure is evidence,
not proof, and it is why the test split exists.

Stuck? A reference rubric is in
[`answer-key/judges/wrong-fact.md`](answer-key/judges/wrong-fact.md). Read it
after your own attempt.

## Exercise 3.4 — the test split, once

Tell your coding agent this is the one test run, and that the rubric is frozen after it:

```bash
uv run python three-day/lab/judge.py three-day/work/judges/grounded.md \
    --split test --mode wrong_fact
```

Write the TPR and TNR in your `criteria.md`, next to the judge's name, with the
date and the model. This is the judge's calibration: the evidence that lets
someone else trust its verdicts. If it is much worse than on dev, the judge
over-fitted the dev runs. Do not keep iterating against test; that turns it into
a second dev split. Label new runs instead.

## Exercise 3.5 — climb

You now have an eval you have measured: code graders checked against your labels,
and a judge checked on runs it never saw. Use it to make the agent better
([concept 13](concepts.md#13-hill-climbing)).

**Hill-climbing** is the loop every team that improves an AI system runs: score,
change one thing, score again, keep the change only if the score went up and
nothing that matters went down. It is easy to do badly. The two ways it goes
wrong are the reason you spent two days on the eval first:

- **It climbs the score, not the quality.** Every false alarm in your graders is
  a "failure" the climb will try to fix. If a grader fails runs where the agent
  sensibly asked the customer a question, the climb will teach the agent to stop
  asking. Before you start, read your false-alarm decisions from 2.3 and fix
  each one in the grader or the case.
- **It fits the cases it climbs on.** Change the agent until 26 cases pass and
  you may have made it better at those 26 and no better, or worse, at the rest.
  So the cases are split in two (`metadata.climb_split` in each case): 26 to
  **climb** on, and 12 **holdout** cases you score once, at the very end.

**Set up.** One score, one log. `score.py` runs every grader in `GRADERS` over a
set of runs, prints the share that passed every one with its interval, and logs
it to `three-day/work/results/climb-log.csv` with the git commit and your note.
It also reports **guardrails** separately: graders that must never get worse,
whatever the score does. Ask your coding agent to make your Day 2 privacy grader
a guardrail beside `refund_within_limit` (the `GUARDRAILS` list in
`lab/score.py`).

**Record a baseline**, three runs of each climb case, and of each holdout case.
Do not score the holdout yet. Recording costs a few cents:

```bash
uv run python three-day/lab/record.py --cases climb --repeat 3 --start 3 \
    --out three-day/traces/climb-00.jsonl
uv run python three-day/lab/record.py --cases holdout --repeat 3 --start 3 \
    --out three-day/traces/holdout-before.jsonl
uv run python three-day/lab/score.py three-day/traces/climb-00.jsonl --note "baseline"
```

(`--start 3` numbers the runs 03 to 05, so they never mix with your labelled dev
and test runs. `record.py` runs the agent through Claude Code by default; add `--via api` to
use `support_agent.agent` with your key instead. Commit before you change
anything, so the log's commit means something.)

**Then climb.** Each round:

1. **Read before you change.** Pick the case with the most failures, read two of
   its failing runs, and say in a sentence what went wrong and why.
2. **Choose one lever.** The agent has three, and the right one depends on the
   cause:
   - **The prompt**, [`agent/prompts/system.md`](agent/prompts/system.md),
     changes what the agent is *told*: when to act, when to hand over, what a
     tool's result means.
   - **Retrieval**, the policy documents in [`agent/corpus/`](agent/corpus/) (or
     how many are handed over, `SUPPORT_AGENT_TOP_K`), changes what it *reads*.
     Your retrieval grader tells you when this is the cause.
   - **The database queries**, the tool handlers in
     [`src/support_agent/sqlite_store.py`](../src/support_agent/sqlite_store.py),
     change what it is *able* to see and do. A leak of another customer's order is
     a permission problem, and the robust fix is a query that will not return it,
     not a prompt that asks nicely.
3. **Make one change**, through your coding agent, and say which. Two changes at
   once and you will not know which one did it.
4. **Record and score:**

   ```bash
   uv run python three-day/lab/record.py --cases climb --repeat 3 --start 3 \
       --out three-day/traces/climb-01.jsonl
   uv run python three-day/lab/score.py three-day/traces/climb-01.jsonl \
       --note "scope lookup_order to the signed-in customer"
   ```

5. **Keep or revert.** `score.py` compares with your baseline and the best so
   far, and lists the cases that now pass more or less often. Keep the change
   (commit it) when it is not WORSE than the best, no guardrail got worse, and
   the cases it moved are the ones you meant it to move. Otherwise revert it.

One round on its own will usually say `can't tell from noise`: 78 runs give an
interval about 20 points wide, and one change typically fixes two or three
cases. That is fine. What has to clear the noise is the climb as a whole,
against the baseline. Expect three or four rounds to get there.

When it does, check one more thing the code graders cannot: that the agent still
sticks to its sources. Score the last climb with your judge too (about $3):

```bash
uv run python three-day/lab/score.py three-day/traces/climb-04.jsonl \
    --judge three-day/work/judges/grounded.md --note "final, with judge"
```

This row is compared only with other rows scored with the same judge, so it
starts its own baseline. Read its failures: a prompt change that makes the agent
more decisive can also make it more willing to state things it has not checked,
and that is the regression the judge catches.

## Exercise 3.6 — the holdout, once

Record the holdout with the agent as it now is, and score both holdout files,
with your judge, once:

```bash
uv run python three-day/lab/record.py --cases holdout --repeat 3 --start 3 \
    --out three-day/traces/holdout-after.jsonl
uv run python three-day/lab/score.py three-day/traces/holdout-before.jsonl \
    --judge three-day/work/judges/grounded.md --note "holdout before"
uv run python three-day/lab/score.py three-day/traces/holdout-after.jsonl \
    --judge three-day/work/judges/grounded.md --note "holdout after"
```

Read the "passes more often" and "passes less often" lines. A lever that fixed a
cause (a query that cannot leak) usually carries over to cases it never saw. A
lever that fixed symptoms (a policy document padded with the words from the
climb cases' messages) often does not, and can break a holdout case that was
fine. If the holdout went down, that is your eval doing its job: it caught an
overfit that the climb score could not see.

Finally, the judge's pass rate is not the real rate, because the judge makes
mistakes at a rate you measured in 3.4. Correct for it:

```bash
uv run python three-day/lab/judge.py three-day/work/judges/grounded.md \
    three-day/traces/holdout-after.jsonl --split all --tpr 0.9 --tnr 0.8   # your numbers from 3.4
```

**Done when** you can finish this sentence with numbers: "Changing ___, ___ and
___ moved the climb score from ___ to ___ (intervals ___) with no guardrail
regression; on holdout cases it never saw, it went from ___ to ___; and the
replies stay grounded by a judge whose TPR and TNR on held-out runs are ___."

That sentence is what an eval is for.

## What you now know how to do

- Write a case as an input plus what a correct run must and must not do.
- Check actions, data and retrieval with code, for free, on every run.
- Find failures nobody wrote a check for, by reading runs and naming what you see.
- Measure agreement between graders, and between people, honestly.
- Build a judge for one failure mode and prove how far to trust it.
- Climb a score one measured change at a time, and check it on cases it never saw.

## Where to go next

The full Agent Eval Forge course goes deeper on each step:

| You did | Go deeper in |
|---|---|
| Day 1 code graders | Ch. 2: threat models, fixtures as inputs, spend control, deterministic scorers |
| Day 2 human labels | Ch. 1: failure taxonomy; Ch. 4.2: blind labelling |
| Day 3 judge | Ch. 3: quote-grounded judges, trajectories; Ch. 4: calibration records, drift, a CI gate |
| Day 3 climb | Ch. 6.3: eval-driven development |
| Not covered here | Ch. 5: red-teaming, including attacks on the judge itself |

Once you trust your eval, the climb can be automated: a loop (the autoresearch
plugin for Claude Code is one) proposes a change, runs `record.py` and
`score.py`, reads the `SCORE` line, and keeps or reverts. Give it your keep
rule, your guardrails and the climb cases only. Keep the holdout for yourself.
An optimiser pointed at an unmeasured score gets very good at pleasing the score.
