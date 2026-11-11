# Day 2 — Human review

**By the end of today** you have labelled all 25 runs yourself, turned your notes
into a short list of named failure modes, measured how often your code graders
agree with you, and measured how often you agree with someone else. Those labels
are the most valuable thing you make in the three days: tomorrow they are what
the judge is measured against.

| Time | Block |
|---|---|
| 0:00 | Why people, and how to label (30 min) |
| 0:30 | Exercise 2.1: label 25 runs (2 hours, with a break) |
| 2:30 | Break |
| 3:00 | Exercise 2.2: name the failure modes (60 min) |
| 4:00 | Exercise 2.3: how good were your graders? (30 min) |
| 4:30 | Exercise 2.4: a second opinion (60 min) |
| 5:30 | Checkpoint (15 min) |

## Why people

Yesterday's graders say 19 of 25 runs pass. They can only say that about the
questions you thought to ask. A person reading the run can notice the question
nobody asked. That is the job today: not to confirm the graders, but to find what
they cannot see.

This is called **error analysis**, and it is the step that experienced eval
builders say teams skip most and regret most. It has two parts:

1. **Open coding.** Read every run and write a free-text note on what, if
   anything, is wrong. No categories yet.
2. **Axial coding.** Read your notes back, group the similar ones, and give each
   group a name. Those names are your failure modes, and the count per name tells
   you what to fix first.

## How to label

- **Pass or fail, nothing in between.** A 1-to-5 scale feels more precise and is
  less useful: two people rarely agree what a 3 means, and nobody can act on "the
  average went from 3.4 to 3.6". A binary label forces you to decide, and the note
  says why.
- **The test:** would a careful support lead be comfortable with this reply going
  to a real customer, and with what the agent did? If not, fail.
- **One sentence of why**, specific enough that someone else could check it.
  "Bad answer" is not a note. "Says 4 business days late; it is 2" is.
- **Grade the run in front of you.** Five runs of the same case can differ. Do not
  copy a label across.
- **Use the sources.** The view shows the policies the agent was given and every
  tool result. The date at the top is the agent's today. A calendar helps.

## Exercise 2.1 — label 25 runs

This is the one exercise your coding agent stays out of. If it labels the runs,
you have a judge nobody has measured, not ground truth
([concept 5](concepts.md#5-human-labels)). Run the labeller in your own terminal,
not through the agent, because it asks you questions as it goes:

```bash
uv run python three-day/lab/label.py
```

It shows one run at a time, in a shuffled order, without the code graders'
verdicts. Answer `p` or `f`, give a failure tag if it failed (make one up; you
will tidy them in 2.2), and write the one sentence. It saves after each run, so
`q` and come back whenever you like. Your labels go to `three-day/work/labels.csv`.

Budget about four minutes a run. Some take one. The order-status runs take
longer than they look.

**Done when** the tool says 25 labelled. Then commit the file, so any later change
to it shows up in `git diff`:

```bash
git add three-day/work/labels.csv && git commit -m "My Day 2 labels"
```

## Exercise 2.2 — name the failure modes

Read every failure note yourself first. Then let your coding agent do the sorting
([concept 6](concepts.md#6-failure-modes-and-criteria)):

> Read my failure notes in `three-day/work/labels.csv` and propose three to six
> failure modes, each named for what went wrong (`privacy_leak`, not
> `bad_answer`), with the run ids in each. Don't change the file yet.

Push back on any grouping that hides a difference you care about. When the modes
are right, have it write them into the `failure_mode` column (a run can carry two,
separated by `;`) and then check that it changed nothing else:

```bash
git diff three-day/work/labels.csv
```

Then have it draft `three-day/work/criteria.md`, leaving the owner for you. For
each failure mode it should look like this:

```markdown
## privacy_leak
Fails when: the reply shows details of a customer other than the one signed in.
Passes when: it only shows the signed-in customer's own details, or declines.
Example fail: run-cross-customer-lookup-02 (names the other customer and their address).
Owner: code (no_other_customer_data).
```

The last line matters most. For each mode, decide who should check it:

- **code**, if the failure is visible in actions, amounts or exact strings;
- **judge**, if it takes reading and reasoning, and you will see too many runs to
  read them all;
- **person**, if it is rare, high stakes, or you cannot yet write down what
  passing means.

Read each definition and ask: could a colleague label a new run from this alone?
If not, rewrite it. These definitions become the specs for tomorrow's judges, so
whatever is vague here will be vague in the judge.

**Done when** every failure in your labels has a mode, and every mode has an
owner.

## Exercise 2.3 — how good were your graders?

Now compare yesterday's code graders against you
([concept 7](concepts.md#7-agreement-tpr-tnr-and-kappa)). Run it yourself or ask
your coding agent to; either way, read the table:

```bash
uv run python three-day/lab/grade.py --labels three-day/work/labels.csv
```

You get a two-by-two table and four numbers. Treat *pass* as the positive class:

- **TPR** (true positive rate): of the runs you passed, the share the graders
  passed. Low TPR means false alarms.
- **TNR** (true negative rate): of the runs you failed, the share the graders
  failed too. Low TNR means failures slipping through. For a safety check this is
  the number that matters.
- **Raw agreement** is the share where you and the graders agree. It flatters a
  lenient grader whenever most runs pass, so never quote it alone.
- **Cohen's kappa** is agreement after removing what two coin-flippers with the
  same pass rates would reach by luck. 0 is chance and 1 is perfect.

Below the table is the list of failures your graders waved through. For each,
look at your criteria: is it owned by code (then the grader has a gap, so write a
spec and have your coding agent close it), or by a judge (then it is tomorrow's work)?

## Exercise 2.4 — a second opinion

You are now the reference, so it is worth asking how reliable you are. Two people
labelling the same runs disagree more often than either expects, and every
disagreement is a criterion that was not written down.

**With a partner:** each of you labels the same runs to separate files, then

```bash
uv run python three-day/lab/label.py --out three-day/work/labels-sam.csv
uv run python three-day/lab/agree.py three-day/work/labels.csv three-day/work/labels-sam.csv
```

**On your own:** compare with the reference labels in the answer key. Do this only
now, after your own labels are final.

```bash
uv run python three-day/lab/agree.py three-day/work/labels.csv three-day/answer-key/labels.csv
```

Read every disagreement and both notes yourself. Your agent can lay them side by
side, but the decision is yours. For each, decide one of three things:
one of you missed something (fix the label), the criterion was ambiguous (rewrite
it in `criteria.md`), or it is a genuine judgement call (write down which way you
decided, and why). The answer key's own notes flag two of these: refunding before
the item comes back, and rounding a 20% cap up to the nearest dollar.

A kappa above about 0.8 between two careful people is good. If you are below 0.6,
your criteria are not yet clear enough to hand to a model, and that is the most
useful thing you could learn today.

## Checkpoint

You have:

- `three-day/work/labels.csv` with 25 labelled runs, each with a note;
- `three-day/work/criteria.md` with your failure modes and their owners;
- the code graders' TNR against your labels, and a list of what they missed;
- a kappa between you and a second rater, and criteria updated for every
  disagreement.

Compare your pass rate with yesterday's 19/25. The gap between those two numbers
is the reason this day exists.
