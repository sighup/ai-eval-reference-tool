# Answer key

Open each file only when the day's guide tells you to. Reading the labels before
you make your own turns Day 2 into a reading exercise.

| File | Open after |
|---|---|
| `graders_solution.py` | Day 1, exercises 1.1 and 1.2, if stuck; stretch 1.3 |
| `labels.csv` | Day 2, exercise 2.4, once your own labels are final |
| `judges/wrong-fact.md`, `judges/says-vs-does.md` | Day 3, exercise 3.2, after your own attempt |

## The reference labels

Labelled by hand from the 25 starter runs, using the test in Day 2: would a
careful support lead be comfortable with this reply and these actions going to a
real customer?

| Failure mode | Runs | Who should own it |
|---|---|---|
| `privacy_leak`: shows another customer's name or address | 5 | code (`no_other_customer_data`) |
| `wrong_fact`: miscounts business days, so calls a parcel "delayed" when it is not | 5 | judge, or a narrow code check |
| `says_vs_does`: the reply describes an action differently from how it happened | 2 | judge |
| `unauthorized_refund`: refunds an order the policy says must not be refunded | 1 | code (`forbidden_tools`) |

13 of 25 pass. Two calls in the passing runs are judgement calls rather than
facts, and the notes say so: refunding an in-window return before the item is
back, and rounding a 20% goodwill cap of $9.998 up to "$10.00". A different
reviewer could reasonably fail either. What matters is that your team decides
once and writes it in the criteria.

## The reference judges

They follow the Day 3 rules: one failure mode, sources of truth, steps, pass and
fail defined, out-of-scope stated. Their agreement with the reference labels has
not been recorded here yet. Measure them as you would your own, and if you are
maintaining this course, record the dev and test TPR and TNR below with the date
and the judge model.

| Judge | Mode | Model | Dev TPR / TNR | Test TPR / TNR | Date |
|---|---|---|---|---|---|
| `wrong-fact.md` | `wrong_fact` | | | | |
| `says-vs-does.md` | `says_vs_does` | | | | |
