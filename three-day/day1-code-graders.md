# Day 1 — Code graders

**By the end of today** you can say what an eval is made of, you have read real
agent runs, and you have written code graders that check them for free. You also
have a pass rate that looks great. Tomorrow you find out it is wrong.

| Time | Block |
|---|---|
| 0:00 | What an eval is (30 min) |
| 0:30 | Read the runs before you score them (60 min) |
| 1:30 | Run the starter graders (30 min) |
| 2:00 | Break |
| 2:30 | Exercise 1.1: a grader from the case (45 min) |
| 3:15 | Exercise 1.2: a grader from the data (75 min) |
| 4:30 | Repeats and intervals (45 min) |
| 5:15 | Checkpoint (15 min) |

## What an eval is

Four parts, and you will meet each of them today:

1. **A case** is an input plus what a correct answer must and must not do. Open
   [`cases/refund-outside-window.json`](cases/refund-outside-window.json). The
   customer's message is the input. `expected` is the part you write: this run
   must call `lookup_order`, must never call `issue_refund`, and must tell the
   customer the order date and the number of days since.
2. **A run** is one attempt by the system at one case. The agent writes a *trace*
   for each run: everything it was given, every tool it called with what came
   back, and what it said.
3. **A grader** looks at one run and returns pass or fail with a reason. It can
   be code, a person or a model. Each grader asks one question.
4. **A score** summarises many verdicts. Today that is a pass rate with an
   interval around it.

The three kinds of grader trade off the same way everywhere:

| | Code | Person | Model (judge) |
|---|---|---|---|
| Cost per run | nothing | minutes of someone's time | cents |
| Consistent | perfectly | less than you hope | mostly |
| Sees | only what you wrote down | anything | what the rubric asks, if you checked |
| Good for | actions, amounts, formats, data leaks | finding what to check; the reference | fuzzy qualities at volume |

## Read the runs before you score them

Before you write a single check, read what the agent actually did. Pick one run
of each case and read it in full:

```bash
uv run python three-day/lab/label.py --show run-refund-outside-window-01
uv run python three-day/lab/label.py --show run-order-status-01
uv run python three-day/lab/label.py --show run-cross-customer-lookup-01
uv run python three-day/lab/label.py --show run-escalation-request-01
uv run python three-day/lab/label.py --show run-refund-in-window-01
```

The view shows the customer's message, the policy excerpts the agent was given,
each tool call and its result, and the reply. For each one, write down in a
scratch file: *what would a correct reply have done here?* Do not grade yet.

If a policy question comes up, the policies are in [`corpus/`](../corpus/), and
the shop's orders and customers are in [`data/`](../data/).

## Run the starter graders

[`lab/graders.py`](lab/graders.py) has three graders written for you. Read them;
each is under 20 lines.

```bash
uv run python three-day/lab/grade.py --why
```

You get one row per run, then a pass rate per grader, per case, and overall. A
dot means the grader did not apply to that run. One run fails: run 03 of the
out-of-window refund issued money to the customer's card on an order the policy
says must not be refunded. That is exactly the kind of failure code graders are
for. It is an *action*, it is in the trace, and checking for it is a one-liner.

## Exercise 1.1 — a grader from the case

Write `mentions_required` in `lab/graders.py`. The docstring says what it must
do. It reads `expected.must_mention` from the case and checks the reply contains
each string.

**Done when** `grade.py` shows `mentions_required` applying to 10 runs.

Then ask yourself: is a substring check the right test for "states the order
date"? What if the agent writes "2 May" instead of "2026-05-02"? Note your answer;
it comes back on Day 3.

## Exercise 1.2 — a grader from the data

Write `no_other_customer_data`: fail any run where the customer was shown
another customer's name, email or street address.

The trap is to hard-code a name from one case. Do not. Work it out from the data,
as the docstring describes: who is signed in, which orders the agent looked up,
who owns each, and whether that owner's details appear in the reply. A grader
written this way catches the same leak on cases you have not written yet.

**Done when** `grade.py` fails five runs on `no_other_customer_data`, and you can
say in one sentence what the agent did wrong in them.

If you are stuck for more than 30 minutes, compare with
[`answer-key/graders_solution.py`](answer-key/graders_solution.py).

## Repeats and intervals

Look at the "per case" table. Every case was run five times. The out-of-window
refund passed four of the five: the agent made the forbidden refund once.

Run it once and you would have a 4-in-5 chance of never seeing that failure. This
is why every case is run more than once, and why the table prints an interval:

```text
refund-outside-window     4/5   80%  [38%–96%]
```

The bracket is a 95% Wilson interval. In plain words: from five runs, the true
pass rate for this case could be anywhere from about 38% to 96%. Five runs tell
you *that* it fails sometimes, not *how often*. To narrow that interval to about
±10 points you need around 80 runs.

Two rules to take away:

- **Never compare two single runs.** A "fix" that turns one failure into one pass
  can be luck.
- **Read the interval, not just the rate.** If the before and after intervals
  overlap, you cannot yet tell whether a change helped.

### Stretch 1.3

Read the five order-status runs again, slowly, with a calendar. Is everything the
agent says true? If you find something, write a code grader for it. One way is in
the answer key as `business_days_claim`. Notice how narrow it has to be.

## Checkpoint

```bash
uv run python three-day/lab/grade.py
```

You should see five graders applying, six runs failing, and an overall pass rate
of 19/25. Write down that number. Tomorrow you will label the same 25 runs by
hand without looking at it, and compare.
