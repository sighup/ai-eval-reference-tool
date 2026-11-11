# Day 3 — LLM-as-judge

**By the end of today** you have a model grading runs against a rubric you wrote,
you know how often it agrees with you on runs it was never tuned on, and you have
used the whole eval (code, judge and your labels) to show whether a change to the
agent made it better.

You need an API key in `.env` today. Budget about $10; the commands print what
each call cost. Every judge verdict is cached, so re-running an unchanged judge
is free.

| Time | Block |
|---|---|
| 0:00 | How a judge goes wrong (20 min) |
| 0:20 | Exercise 3.1: the naive judge (40 min) |
| 1:00 | Exercise 3.2: a judge for one failure mode (2 hours, with a break) |
| 3:00 | Exercise 3.3: the test split, once (30 min) |
| 3:30 | Break |
| 4:00 | Exercise 3.4: did the fix work? (90 min) |
| 5:30 | Where to go next (15 min) |

## How a judge goes wrong

A judge is a model with a rubric. It is cheap, it reads everything, and it can
check qualities code cannot. It also fails in quiet ways: it is lenient, it is
persuaded by confident prose, it checks the question you asked rather than the
one you meant, and it can be fooled by the very text it is grading. You do not
find out which of these your judge does by reading its prompt. You find out by
measuring it against labels you trust, which you made yesterday.

The rules this course follows:

- **One judge per failure mode, pass or fail.** "Is this good?" is several
  questions. A judge for `wrong_fact` asks one.
- **Critique first, verdict second.** `judge.py` makes the model write its
  reasoning before it commits. You will read those critiques whenever it
  disagrees with you.
- **Tune on dev, report on test.** Runs numbered 01 and 02 are the dev split:
  read them, iterate on them. Runs 03 to 05 are the test split: score once, at
  the end, and report that number. A judge tuned until it agrees with you on the
  runs you tuned it on proves nothing.
- **Report TPR and TNR, not accuracy.** A judge that passes everything agrees
  with you every time the agent was right.

## Exercise 3.1 — the naive judge

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

## Exercise 3.2 — a judge for one failure mode

Pick one failure mode from your `criteria.md` that you marked **judge**. If you
followed the course, `wrong_fact` (the business-day miscount) or `says_vs_does`
(the reply describes an action differently from how it happened) are good
choices: neither shows up as a wrong tool call, so code cannot see it without a
grader narrow enough to break on the next phrasing.

```bash
mkdir -p three-day/work/judges
cp three-day/judges/naive.md three-day/work/judges/wrong-fact.md
```

Rewrite it. A rubric that works usually has:

1. **One question**, stated first, with the failure mode's name.
2. **The sources of truth**: what the judge should treat as correct (tool
   results, policy excerpts, today's date) and what it should not trust (the
   agent's own claims).
3. **How to check**: the steps you took yesterday when you caught this failure.
   If you counted business days on a calendar, tell the judge to write the dates
   out.
4. **Pass and fail, defined.** Copy from `criteria.md`.
5. **What is out of scope.** Tell it what *not* to fail for, or it will fail
   runs for everything else it notices.
6. `{{run}}` where the run goes.

Run it against just that failure mode:

```bash
uv run python three-day/lab/judge.py three-day/work/judges/wrong-fact.md \
    --split dev --mode wrong_fact
```

With `--mode`, a run counts as a reference fail only if you failed it with that
tag. Iterate: read each disagreement, change the rubric for a reason that would
hold on runs you have not seen, and run again. Do not paste facts from a
particular run into the rubric ("the B-5527 order is 2 business days late"):
that is the judge learning the test, and it will not survive the test split.

**Done when** the judge agrees with you on every dev run, or you can explain each
remaining disagreement. Be honest about the numbers: the dev split has ten runs,
and perhaps two of them fail for your mode. A perfect score on two failures is
evidence, not proof.

Stuck? Two reference rubrics are in
[`answer-key/judges/`](answer-key/judges/). Read them after your own attempt.

## Exercise 3.3 — the test split, once

```bash
uv run python three-day/lab/judge.py three-day/work/judges/wrong-fact.md \
    --split test --mode wrong_fact
```

Write the TPR and TNR in your `criteria.md`, next to the judge's name, with the
date and the model. This is the judge's calibration: the evidence that lets
someone else trust its verdicts. If it is much worse than on dev, the judge
over-fitted the dev runs. Do not keep iterating against test; that turns it into
a second dev split. Label new runs instead.

## Exercise 3.4 — did the fix work?

Now use everything. First, a fresh baseline: the recorded runs were made months
ago, so record your own "before" with the agent exactly as it is (about $0.60):

```bash
for case in three-day/cases/*.json; do
  uv run support-agent run --fixture "$case" --repeat 5 --trace-out traces/before.jsonl
done
```

Pick the failure mode with the most failures in your labels and fix its cause.
The agent has three surfaces you can change, and the right one depends on the
failure:

- [`prompts/system.md`](../prompts/system.md) changes what the agent is *told*.
  A miscount might be fixed by telling it how to count.
- [`src/support_agent/tools.py`](../src/support_agent/tools.py) changes what it is
  *able* to do. A leak of another customer's data is a permission problem, and
  the robust fix is a tool that will not return another customer's order, not a
  prompt that asks nicely.
- [`corpus/`](../corpus/) changes the policies it reads.

Change one thing. Then record "after" and compare, with your judge included:

```bash
for case in three-day/cases/*.json; do
  uv run support-agent run --fixture "$case" --repeat 5 --trace-out traces/after.jsonl
done
uv run python three-day/lab/compare.py traces/before.jsonl traces/after.jsonl \
    --judge three-day/work/judges/wrong-fact.md
```

For each grader and each case you get the before and after rate, both
intervals, and a call: `better`, `WORSE` or `can't tell`. Look at the rows you
were *not* trying to fix too. A prompt change that fixes the count and breaks
refunds is a regression, and this is where you catch it.

Finally, the judge's pass rate on the new runs is not the real pass rate, because
the judge makes mistakes at a rate you measured in 3.3. Correct for it:

```bash
uv run python three-day/lab/judge.py three-day/work/judges/wrong-fact.md \
    traces/after.jsonl --split all --tpr 0.9 --tnr 0.8   # your numbers from 3.3
```

**Done when** you can finish this sentence with numbers: "Changing ___ moved
___ from ___ to ___ (intervals ___), with no regression in ___, measured by a
judge whose TPR and TNR on held-out runs are ___."

That sentence is what an eval is for.

## What you now know how to do

- Write a case as an input plus what a correct run must and must not do.
- Check actions and data with code, for free, on every run.
- Find failures nobody wrote a check for, by reading runs and naming what you see.
- Measure agreement between graders, and between people, honestly.
- Build a judge for one failure mode and prove how far to trust it.
- Show whether a change helped, with intervals, without fooling yourself.

## Where to go next

The full Agent Eval Forge course goes deeper on each step:

| You did | Go deeper in |
|---|---|
| Day 1 code graders | Ch. 2: threat models, fixtures as inputs, spend control, deterministic scorers |
| Day 2 human labels | Ch. 1: failure taxonomy; Ch. 4.2: blind labelling |
| Day 3 judge | Ch. 3: quote-grounded judges, trajectories; Ch. 4: calibration records, drift, holdout splits, a CI gate |
| Day 3 fix and compare | Ch. 6.3: eval-driven development |
| Not covered here | Ch. 5: red-teaming, including attacks on the judge itself |

Once you trust your eval, the fix-and-compare loop can be automated: an
optimiser proposes small prompt changes, scores them on a training split, and
keeps one only if it also wins on a validation split it never tuned against.
That only works because of today. An optimiser pointed at an unmeasured judge
gets very good at pleasing the judge.
