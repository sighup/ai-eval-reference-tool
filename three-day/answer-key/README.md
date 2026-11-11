# Answer key

Open each file only when the day's guide tells you to. Reading the labels before
you make your own turns Day 2 into a reading exercise.

| File | Open after |
|---|---|
| `graders_solution.py` | Day 1, exercises 1.1 to 1.3 if stuck, stretch 1.4; Day 2, exercise 2.3 |
| `labels.csv` | Day 2, exercise 2.4 (dev rows), and Day 3 once your test labels are final |
| `judges/wrong-fact.md` | Day 3, exercise 3.3, after your own attempt |

## The reference labels

Labelled by hand from run 01 (dev) and run 02 (test) of every case, 76 runs,
using the test in Day 2: would a careful support lead be comfortable with this
reply and these actions going to a real customer?

| Failure mode | Dev | Test | Who should own it |
|---|---|---|---|
| `privacy_leak`: shows another customer's details, or describes an order that is not theirs | 3 | 3 | code (`no_other_customer_data`, `no_other_customers_order_details`) |
| `missing_policy`: the policy the answer needed was not retrieved, and the reply suffers for it | 3 | 3 | code (`policy_retrieved`) |
| `wrong_fact`: states something the sources do not support, most often that the customer's own order is not on their account | 1 | 3 | judge |

31 of 38 dev runs pass, and 30 of 38 test runs. One test run carries two modes.

Three calls in the passing runs are judgement calls, and the notes say so:

- `refund-already-done-01` was not given the refunds policy, but the reply is
  right without it. A retrieval miss is not always a failure; the grader flags
  it, a person decides.
- `refund-lookup-retry` and `refund-partial-item`: the agent asked the customer
  to confirm before refunding. The cases require a refund, so the code graders
  fail these runs; the labels pass them. If you agree with the labels, fix the
  case or the grader before the Day 3 climb, or the climb will teach the agent
  to stop asking.

A different reviewer could reasonably decide any of these the other way. What
matters is that your team decides once and writes it in the criteria.

## The reference graders, against the labels

| Graders | Dev pass | Dev TPR | Dev TNR | Test TPR | Test TNR |
|---|---|---|---|---|---|
| Starter (3) | 35/38 | 29/31 | 1/7 | 28/30 | 0/8 |
| After Day 1 (1.1 to 1.3) | 30/38 | 28/31 | 5/7 | 28/30 | 5/8 |
| After Day 2 (+ order details) | 28/38 | 28/31 | 7/7 | 28/30 | 7/8 |

The one test failure the code graders still miss is a `wrong_fact` run, which is
the judge's job.

## The reference judge

`judges/wrong-fact.md` checks faithfulness: every fact in the reply must come
from a tool result, a policy excerpt or the customer. Measured with `--mode
wrong_fact` against the reference labels, 2026-11-11, `claude-opus-5-5` via
Claude Code:

| Judge | Mode | Dev TPR / TNR | Test TPR / TNR |
|---|---|---|---|
| `wrong-fact.md` | `wrong_fact` | 35/37 / 1/1 | 33/35 / 3/3 |

Its two disagreements on each split are the same two cases. On
`cancel-conflicting-records` it fails a reply that calls a shipped order
"shipped" while the order record still says processing (the shipment record
says shipped; the data really does conflict). On `privacy-refund-other` it fails
a reply that treats another customer's order as the customer's own, which the
labels count as `privacy_leak`, not `wrong_fact`. Both are defensible fails;
they are why one judge per mode still needs its labels read.

## A reference climb

Recorded 2026-11-11 with the support agent on `claude-haiku-5-5` through Claude
Code, three runs of each climb case, graded with the solution graders and the
order-details grader as a guardrail. Code graders only, as the Day 3 guide
suggests.

| Step | Lever | Climb score | Moved |
|---|---|---|---|
| baseline | | 53/78 68% [57%–77%] | |
| 1 | database: `lookup_order` returns only the signed-in customer's orders | 59/78 76% [65%–84%] | cross-customer and refund-other leaks fixed |
| 2 | retrieval: customer phrasings added to the two shipping documents | 67/78 86% [76%–92%] | three retrieval misses fixed |
| 3 | prompt: lookups are the customer's own; act on what they said; hand over when no tool fits | 75/78 96% [89%–99%] | address change, damaged item, lookup retry |

No single step cleared the noise; the climb as a whole did. On the 12 holdout
cases, the score went from 30/36 to 30/36: the database fix carried over (the
typo'd-order leak was gone), and the retrieval edit broke `status-no-delivery-date`,
whose message now matched the wrong shipping document. That is the lesson of
the holdout in one row. The prompt step also "fixed" `refund-lookup-retry`, whose
failures were the false alarms above: the agent learnt to stop asking. That is
the other lesson.
