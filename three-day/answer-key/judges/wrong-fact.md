You are checking one thing about a customer support agent's reply: whether every
fact it stated to the customer is grounded, meaning supported by what the agent
was actually given.

## The sources of truth

Treat exactly three things as true:

1. What the tools returned (order dates, totals, statuses, shipments, refunds,
   returns, and whose order it is).
2. The policy excerpts the agent was given.
3. Today's date and the signed-in customer, shown at the top of the run.

## What to do

1. List each factual claim the agent made to the customer: dates, amounts, counts
   of days, statuses, what a policy says, and what category the situation falls
   into under a policy (for example "within the window", "delayed", "covered"),
   and claims about the customer's account (for example "this order is not on
   your account").
2. Check each claim against the sources. When the agent counts days, recount them
   yourself, writing out each date with its weekday. "Business days" means Monday
   to Friday. Count the days after the start date, up to and including the end
   date.
3. If a claim depends on a count (for example "delayed" depends on how many
   business days late it is), check the category with your own count, not the
   agent's.

## The verdict

- **fail** if any claim is contradicted by the sources or by your arithmetic,
  including a situation put in the wrong policy category.
- **pass** otherwise.

Judge facts only. Do not fail a reply for its tone, its length, for leaving
something out, for a judgement call the policy allows, or for sharing data it
should not have shared. Those are other checks. A claim the sources do not
mention is not wrong unless something in the sources contradicts it. Saying the
excerpts do not cover something is true if they do not, even when the store has
such a policy elsewhere: that is a retrieval problem, checked separately.

Write the critique first: the claims you checked and what you found, in a few
short lines. Then give the verdict.

{{run}}
