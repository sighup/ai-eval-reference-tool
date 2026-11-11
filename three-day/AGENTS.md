# Instructions for a coding agent working with a three-day learner

The person you are working with is learning to build evals in three days. They
direct; you build. The course is in `three-day/README.md`, the day guides, and
`three-day/concepts.md`. Read `concepts.md` before your first task: the learner
will use its vocabulary, and its "check it yourself" lines are what they will
check you against.

Two agents are involved. **The support agent** (`src/support_agent/`) is the
system being evaluated. **You** are the coding agent.

## What the learner does, and you must not

- **Labels.** Never write or change a `label` value in any
  `three-day/work/labels*.csv`. Human labels are the ground truth; if you produce
  them, the course measures you against yourself. You may edit the
  `failure_mode` and `note` columns when asked, and you show `git diff` of the
  file afterwards. `label.py` is interactive: tell the learner to run it in their
  own terminal.
- **The answer key.** Do not open, read, search or quote anything under
  `three-day/answer-key/` unless the learner says the guide tells them to open it
  at this step. If a search would cover it, exclude it.
- **Deciding.** What counts as a failure, which failure to fix, and how to fix it
  are the learner's calls. Offer options with reasons; do not choose for them.

## How to build what they ask for

- **Graders** (`three-day/lab/graders.py`). A good request has five parts: the
  yes/no question, pass and fail defined, what it may read, what it returns when
  it does not apply, and which runs should fail. If one is missing, say which and
  suggest one before writing code. Add new graders to `GRADERS`.
- **Judges** (`three-day/work/judges/*.md`). One failure mode per judge, with
  `{{run}}` where the run goes. Build the rubric from the learner's
  `three-day/work/criteria.md`. Show the prompt before running it.
- **No facts from particular runs** in any grader or judge: no customer names,
  order ids, dates or amounts copied from a trace. Derive them from the case, the
  trace or the database. If a rule seems to need one, say so instead of adding it. This
  is the most common way an eval ends up passing its own examples and nothing else.
- After changing a grader, run `uv run python three-day/lab/grade.py --why` and
  show the output. After changing a judge, run it on the dev split and show every
  disagreement with the learner's note beside it.

## The splits

Labels are split by run number (`common.split_of`): run 01 of every case is
**dev**, run 02 is **test**, and runs 03 and up are never labelled.

- Run `judge.py --split test` only when the learner asks for the test run in so
  many words. After it, do not edit that judge file; if they want to change it,
  remind them that the test number then no longer means anything.
- Never tune a grader or judge by looking at how it does on test runs, or on
  `--split all` of the recorded traces.

Cases are split for the Day 3 climb (`metadata.climb_split`): **climb** and
**holdout**.

- Record and score holdout cases only when the learner asks for the holdout
  check in so many words: once to record the "before" at the start of the climb
  (do not score it then), and once at the end.
- Never propose or make a change to the support agent because of how it does on
  a holdout case, and never read holdout runs to look for ideas.

## Hill-climbing

On Day 3 the learner climbs `score.py` by changing the support agent. Each round:
show the worst cases and two failing runs, propose which lever (prompt in
`three-day/agent/prompts/`, documents in `three-day/agent/corpus/`, or the tool
queries in `src/support_agent/sqlite_store.py`) would fix the cause, and wait
for the learner to choose. Then make exactly that one change, record the climb
cases (`record.py --cases climb --repeat 3 --start 3`), run `score.py` with a
`--note` saying what changed, and show the whole output. Commit a kept change;
revert one the learner rejects.

- Fix causes, not cases. A document padded with the words from one case's
  message, or a prompt line about one customer or order, is the climb fitting its
  examples. If that is the only fix you can see, say so.
- The two `Planted flaw` comments in `sqlite_store.py` mark the course's
  deliberate bugs. Leave them unless the learner chooses that lever.

## Reporting

- Report pass rates with their intervals, as the tools print them. When
  `score.py` says `can't tell from noise`, say that; do not call it an
  improvement.
- Quote TPR and TNR together, never raw agreement alone.

## Money

`judge.py`, `record.py` and `score.py --judge` call a model and cost money,
through the API or the learner's Claude Code. Before a call over more than a
handful of runs, give the estimate (`judge.py --dry-run` prints one; a recorded
run of the support agent is about $0.001, a judged run about $0.02–0.04) and
wait for a yes if it is over about $2.

## Leave alone unless asked

`three-day/traces/baseline*.jsonl`, `three-day/db/`, `three-day/cases/`, and the
harness files in `three-day/lab/` other than `graders.py`. Change a case only
when the learner has decided, on Day 2 or 3, that it asks for the wrong thing,
and show `git diff` of it. The support agent's prompt, documents and tool
queries change only in the Day 3 climb, one learner-chosen change at a time.
