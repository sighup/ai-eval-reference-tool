# Progress checker

Learner-facing **Check your progress** Action for this harness.

## How to use it

1. Open **Actions → Check your progress**.
2. Choose a **chapter** (single check) or **all chapters** (full scorecard).
3. Read the run summary scorecard.

It scores the **current checkout** of this repository (files, shapes, and counts). Re-run anytime.

## What it is not

- Not a merge gate — it never blocks PRs or protects branches.
- Not a certificate — passing the scorecard does not certify course completion.
- Not a forge cross-repo grader — no cloning other repos, no OCTO-STS, no AI grade job.

## Honest limit

Deterministic checks cover **files, shapes, and counts**. They cannot tell human judgement from agent-authored prose that satisfies the same schema.

## Layout

| Path | Purpose |
| --- | --- |
| `chapter-verification.json` | Per-chapter check registry |
| `../scripts/*.mjs` | Deterministic scorecard pipeline |
| `../scripts/__fixtures__/{complete,incomplete}` | Offline scorecard fixtures |
| `../workflows/check-progress.yml` | The Action |

## Local fixture mode

```bash
GITHUB_ACTOR=you \
LEARNER_REPO_DIR=.github/scripts/__fixtures__/complete \
CHAPTER='all chapters' \
node .github/scripts/check-deterministic.mjs
```

```bash
npm run test:progress
```
