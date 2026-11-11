# Day 1 — Code graders

**By the end of today** you can say what an eval is made of, you have read real
runs of the support agent, and you have had your coding agent build code graders
to your spec and proved they check what you meant. You also have a pass rate that
looks great. Tomorrow you find out it is wrong.

| Time | Block |
|---|---|
| 0:00 | What an eval is (30 min) |
| 0:30 | Read the runs before you score them (60 min) |
| 1:30 | Run the starter graders (30 min) |
| 2:00 | Break |
| 2:30 | How to get a grader built (20 min) |
| 2:50 | Exercise 1.1: a grader from the case (40 min) |
| 3:30 | Exercise 1.2: a grader from the data (60 min) |
| 4:30 | Repeats and intervals (45 min) |
| 5:15 | Checkpoint (15 min) |

You will not write code in this course. Your coding agent writes it, in the
session you started during setup. Your job is the part it cannot do for you:
deciding what to check, saying so precisely, and proving that what it built
checks that. "The agent" in these guides means the support agent being evaluated;
"your coding agent" means the one you direct.

## What an eval is

Four parts, and you will meet each of them today:

1. **A case** is an input plus what a correct answer must and must not do. Open
   [`cases/refund-outside-window.json`](cases/refund-outside-window.json). The
   customer's message is the input. `expected` is the part a person decides: this run
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

Before you ask for a single check, read what the support agent actually did. Pick one run
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

[`lab/graders.py`](lab/graders.py) has three graders already. Ask your coding agent to
walk you through one; each is under 20 lines. You do not need to be able to write
them, but you should be able to say what each one checks and what it would miss.

```bash
uv run python three-day/lab/grade.py --why
```

You get one row per run, then a pass rate per grader, per case, and overall. A
dot means the grader did not apply to that run. One run fails: run 03 of the
out-of-window refund issued money to the customer's card on an order the policy
says must not be refunded. That is exactly the kind of failure code graders are
for. It is an *action*, it is in the trace, and checking for it is a one-liner.

## How to get a grader built

This section is concept 3 in [the concepts guide](concepts.md#3-code-grader); keep
that page open from here on.

A coding agent will write a grader in seconds, and it will look right. Whether it
*is* right is your job, and it comes down to two habits.

**Write a spec, not a wish.** "Check for privacy problems" gets you a guess. A
grader spec answers five things:

1. **The one question**, as a yes/no.
2. **What passes and what fails**, in a sentence each.
3. **What it may read**: the case's `expected` block, the trace, the shop's data in
   `data/`. And what it must not do, such as hard-code a value from one run.
4. **What to return when it does not apply**, so it is skipped rather than passed.
5. **Which runs you expect to fail**, from your reading this morning. This is the
   test the grader has to pass.

**Check it against runs you have read.** Ask the agent to run
`uv run python three-day/lab/grade.py --why` and show you the output. Then check
three things yourself:

- The runs you predicted would fail do fail, for the reason you meant.
- Runs you know are fine still pass. A grader that fails everything is as useless
  as one that passes everything.
- The code has no names, ids or dates from a particular run in it. If it does, it
  will pass the run it was written for and miss the next one.

If any of those is off, say what you saw and ask for a fix. That loop (spec, run,
compare with what you know) is the same one you will use on the judge on Day 3.

## Exercise 1.1 — a grader from the case

The stub `mentions_required` in `lab/graders.py` should check that the reply states
every string listed under `expected.must_mention` in the case. Here is a spec for
it, as an example of the shape. Read it, change anything you disagree with, and
give it to your coding agent:

> Implement `mentions_required` in `three-day/lab/graders.py`.
> 1. Question: did the customer get told every fact the case lists under
>    `expected.must_mention`?
> 2. Fail if any listed string is missing from what the customer was shown
>    (`customer_text(run)`), naming the missing ones in the reason; pass otherwise.
> 3. Read the strings from the case. Do not hard-code any of them.
> 4. If the case lists nothing, return `Verdict(None, ...)`.
> 5. I expect it to apply to the 10 out-of-window and order-status runs. Run
>    `grade.py --why` and show me the output.

**Done when** `grade.py` shows `mentions_required` applying to 10 runs, and you
have checked by reading that at least one of them really does say the order date.

Then ask yourself: is a substring check the right test for "states the order
date"? What if the reply says "2 May" instead of "2026-05-02"? Note your answer;
it comes back on Day 3.

## Exercise 1.2 — a grader from the data

`no_other_customer_data` should fail any run where the customer was shown another
customer's name, email or street address. Before you write the spec, read
`run-cross-customer-lookup-02` again and work out who is signed in and whose order
was read out.

The trap here is the one a coding agent falls into most readily: it sees one
leaked name and checks for that name. Your spec has to say how to work it out from
the data instead: who is signed in, which orders the agent looked up, who owns
each, and whether that owner's details appear in the reply. A grader written that
way catches the same leak on cases nobody has written yet.

This time, write the spec yourself. The skeleton:

> Implement `no_other_customer_data` in `three-day/lab/graders.py`.
> 1. Question: ...
> 2. Fail if ...; pass otherwise.
> 3. Read ... from the trace and ... from `data/`. Do not hard-code ...
> 4. If ..., return `Verdict(None, ...)`.
> 5. I expect these runs to fail: ... Run `grade.py --why` and show me the output.

**Done when** `grade.py` fails exactly the five cross-customer runs on
`no_other_customer_data`, the code contains no customer's name, and you can say in
one sentence what the agent did wrong in those runs.

If it is still not right after a few rounds, compare with
[`answer-key/graders_solution.py`](answer-key/graders_solution.py). Tell your
agent you are doing so; it is told to stay out of the answer key otherwise.

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
agent says true? Find it yourself before you ask your coding agent; finding it is the
skill. If you find something, spec a code grader for it, and look at what the
agent has to do to make it work. One way is in the answer key as
`business_days_claim`. Notice how narrow it has to be.

## Checkpoint

```bash
uv run python three-day/lab/grade.py
```

You should see five graders applying, six runs failing, and an overall pass rate
of 19/25. Write down that number. Tomorrow you will label the same 25 runs by
hand without looking at it, and compare.
