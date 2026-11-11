# The concepts, and how to direct a coding agent with them

You will not write code in this course. A coding agent will. What it cannot do
is decide what "correct" means, or notice when what it built only looks correct.
That is your job, and it needs the concepts below.

Two agents appear on this page. **The support agent** is the system being
evaluated: it answers Northwind Goods customers. **Your coding agent** is the one
you direct: it writes graders and judges, runs the tools, and makes fixes.

Each concept has three parts:

- **The idea**, in plain words.
- **Ask for it like this**: the words that get your coding agent to build the right thing.
  Adapt them; do not paste them blind.
- **Check it yourself**: how you tell, without reading every line, that your coding agent did what you meant.

Keep this page open beside your coding agent session. The day guides link back here.

---

## 1. Case

**The idea.** One input to the system, plus what a correct run must and must not
do. The input is the customer's message. The "must and must not" is the part you
write, and it is where most of an eval's value comes from.

**Ask for it like this.**

> Add a case to `three-day/cases/` for a customer asking to cancel an order
> that has already shipped. Pick a real shipped order from the database for a
> customer who owns it. A correct run must call `lookup_order` and must not call
> `cancel_order` or `issue_refund`, and needs `kb-orders-01`. Follow the shape of
> the existing cases, including `metadata.why` and `metadata.climb_split`.

**Check it yourself.** Read the `expected` block. Every line in it should be
something you would fail a run for. If you would not fail a run over it, take it
out.

## 2. Run and trace

**The idea.** A run is one attempt at one case. Its trace is the full record:
what the support agent was given, every tool it called and what came back, and what it
said. Everything you grade, you grade from the trace.

**Ask for it like this.**

> Show me run `run-status-split-shipment-01` with `label.py --show`, then tell me in two
> sentences what the support agent did and what it told the customer.

**Check it yourself.** Read at least one run of every case in full yourself,
before you ask for any grader. Your coding agent summarising a run for you is useful; it is
not the same as having seen it.

## 3. Code grader

**The idea.** A small function that answers one yes/no question about a run:
"did it call a tool it must not?", "did it refund more than the order total?".
Free, instant, never changes its mind. Blind to anything you did not tell it to
look for.

**Ask for it like this.** Give a spec with five parts:

> Write a grader `escalation_names_order` in `three-day/lab/graders.py` and add
> it to `GRADERS`.
> 1. Question: when the support agent handed over to a person, did its summary name the
>    order the customer asked about?
> 2. Fail if an `escalate_to_human` summary leaves out the id of every order the support agent looked up; pass if it names one.
> 3. Read the summary and the looked-up order ids from the trace's tool calls. Do
>    not hard-code any order id.
> 4. If the run did not escalate, return `Verdict(None, ...)` so it is skipped.
> 5. I expect every escalation in the recorded runs to pass. Run `grade.py --why`
>    and show me the output.

**Check it yourself.** Three checks, every time:

- The runs you expected to fail, fail, and the reason printed is the one you meant.
- Runs you know are fine still pass.
- The code contains no name, id, date or amount copied from one run. If it does,
  it was written to pass a test, not to check a rule.

## 4. Repeats and intervals

**The idea.** The same input does not give the same run twice. One run tells you
almost nothing. Run each case several times and report a pass rate with an
interval: "4 of 5, somewhere between 38% and 96%". Two results whose intervals
overlap cannot yet be told apart.

**Ask for it like this.**

> Record every case in `three-day/cases/` five times with `record.py` into
> `three-day/traces/before.jsonl`, then run `grade.py` on that file and show me
> the per-case table with intervals.

**Check it yourself.** Every case should show `n/5`, not `n/1`. When your coding agent says a change "fixed" something, ask for the before and after intervals. If they
overlap, it has not shown that yet.

## 5. Human labels

**The idea.** You read a run and say pass or fail, with one sentence of why.
These labels are the ground truth everything else is measured against. They have
to be yours. If your coding agent labels the runs, you have an unmeasured judge, not
ground truth.

**Ask for it like this.** You don't. Run `label.py` in your own terminal. What
you *can* ask for:

> Read my notes in `three-day/work/labels.csv` and suggest how to group the
> failure notes into three to six named failure modes. Don't change any label.

**Check it yourself.** Every label in the file is one you typed. Use
`git diff three-day/work/labels.csv` after any coding agent session to make sure.

## 6. Failure modes and criteria

**The idea.** The names you give to the kinds of failure you found, each with a
pass/fail definition, an example, and an owner: code, judge, or person. Written
in `criteria.md`. This is the specification every grader and judge is built from.

**Ask for it like this.**

> Draft `three-day/work/criteria.md` from my labels. For each failure mode: a
> one-line "fails when", a one-line "passes when", one example run id, and leave
> the owner blank for me to fill in.

**Check it yourself.** Could a colleague label a new run using only
`criteria.md`? If a definition needs you to explain it, rewrite it.

## 7. Agreement: TPR, TNR and kappa

**The idea.** How far a grader (or another person) matches your labels. Treat
*pass* as positive:

- **TPR**: of the runs you passed, the share it also passed. Low means false alarms.
- **TNR**: of the runs you failed, the share it also failed. Low means failures
  get through. For anything that matters, watch this one.
- **Kappa**: agreement after discounting luck. 0 is chance, 1 is perfect, above
  about 0.8 is strong.
- **Raw agreement** flatters a lenient grader. Never quote it alone.

**Ask for it like this.**

> Run `grade.py --labels three-day/work/labels.csv` and list the runs I failed
> that the graders passed, with my note for each.

**Check it yourself.** Look at the two-by-two table, not only the summary line.
The top-right cell is failures waved through: read every run in it.

## 8. LLM judge

**The idea.** A model grading a run against a rubric you wrote. It can check
things code cannot, like whether a stated fact is true. It is also lenient,
persuadable, and checks the question you wrote rather than the one you meant.
Build one judge for each failure mode, each answering pass or fail, with its
reasoning written before the verdict.

**Ask for it like this.**

> Draft a judge prompt at `three-day/work/judges/grounded.md` for the
> `wrong_fact` failure mode in my `criteria.md`. Structure: the one question; the
> sources of truth (tool results including whose order it is, policy excerpts,
> today's date, who is signed in); the steps to check, starting with listing
> every factual claim in the reply; pass and fail defined; what is out of scope;
> `{{run}}` at the end. Use no facts from any particular run.

**Check it yourself.** Read the rubric before it runs. Could it pass a run you
failed? Does it mention a specific order, date or name? If so, it has been
written to the examples.

## 9. Dev and test split

**The idea.** Tune on some runs (dev: run 01 of every case), report on others you
never tuned on (test: run 02). Runs 03 and up are never labelled. A judge adjusted until it agrees with you on the
runs it was adjusted on proves nothing. A coding agent asked to "make the judge
agree with my labels" will, if you let it, use the test runs to get there.

**Ask for it like this.**

> Run the judge on the dev split with `--mode wrong_fact`. For each disagreement,
> show me its critique and my note side by side, and propose one general change
> to the rubric. Don't run the test split.

Later, once:

> Now run it on the test split, once, and give me the TPR and TNR. Don't change
> the rubric after this.

**Check it yourself.** `git log` on the judge file: no change after the test run.
And the number you report is the test number, not the dev number.

## 10. Calibration and the corrected pass rate

**The idea.** The judge's TPR and TNR on the test split are its calibration: the
evidence for how far to trust it. Because you know how often it is wrong, you can
correct its pass rate on new runs to estimate the real one.

**Ask for it like this.**

> Record the judge's test TPR and TNR, the model, and today's date in
> `criteria.md`. Then run it on `three-day/traces/holdout-after.jsonl` with
> `--split all` and those numbers as `--tpr` and `--tnr`, and show me the
> observed and corrected pass rates.

**Check it yourself.** If TPR + TNR is not comfortably above 1, the judge is
close to a coin flip and its numbers mean nothing. The tool will say so.

## 11. Before and after

**The idea.** A change is only an improvement if the eval shows it: the target
failure went down, its interval separated from the before interval, and nothing
else got worse. Change one thing at a time, or you will not know which change did
it. Concept 13 turns this into a loop.

**Ask for it like this.**

> Make one change: [the fix you decided on]. Record the climb cases again with
> `record.py`, run `score.py` on the new file with a note saying what changed,
> and show me the whole output, including the cases that pass less often.

**Check it yourself.** You decided the fix, from your failure modes. Your coding
agent made one change, and you can say which. Nothing says `WORSE`, and no
guardrail got worse.

## 12. Grounding: retrieval and faithfulness

**The idea.** An agent that answers from documents can go wrong in two separate
places, and each needs its own check. **Retrieval**: was it handed the right
sources? That is a code grader, because each case can list the documents a
correct answer needs, and the trace records which ones it got. **Faithfulness**:
did the reply stick to the sources it had, or did it state things they do not
support? That takes reading, so it is a judge. Keep them apart. A judge that
also fails runs for missing documents is checking two things, and when it fails
you will not know which.

**Ask for it like this.**

> Implement `policy_retrieved`: fail when the agent was not given a document the
> case lists under `expected.policy_docs`, naming the missing one; skip cases
> that list none.

and, separately,

> Draft a faithfulness judge: every fact the reply states must come from a tool
> result, a policy excerpt or the customer's message. Tell it that whether the
> right documents were retrieved is out of scope.

**Check it yourself.** For a run that fails retrieval, read the reply: did the
missing document change the answer? Sometimes it does not, and that is a false
alarm you decide about. For the judge, find one run where the reply says
something no source supports, and confirm the judge fails it for that reason.

## 13. Hill-climbing

**The idea.** Score the system, change one thing, score again, and keep the
change only if the score did not get worse, no guardrail got worse, and it moved
the case you aimed at, and any case that dropped was read and the drop was not
caused by the change. Repeat. The agent has three kinds of lever: what it is
told (the prompt), what it reads (retrieval and the documents), and what it can
see and do (the tools and their database queries). Two rules keep the climb
honest: climb on one set of cases and check the result once on a **holdout** set
the climb never saw, and fix the score's false alarms before you start, because
the climb will chase them.

**Ask for it like this.**

> Score `three-day/traces/climb-00.jsonl` with `score.py` and show me the cases
> with the most failures. For the worst one, show me two failing runs and tell me
> which lever (prompt, retrieval or database query) you think would fix the
> cause, and why. Don't change anything yet.

Then, once you have decided:

> Make that one change. Record the climb cases with `record.py --cases climb
> --repeat 3 --start 3`, score them with a note, and tell me whether my keep rule
> says keep or revert.

**Check it yourself.** `three-day/work/results/climb-log.csv` has one row per
change, each with a note you recognise. Nothing was tuned on the holdout cases.
And the final holdout score is the number you report, not the climb score.
