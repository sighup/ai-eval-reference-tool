import assert from 'node:assert/strict';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { matchGlob, validateHarnessFixture, HARNESS_LIFECYCLES } from './verify-completion-evidence.mjs';
import { runDeterministicCheck } from './check-deterministic.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const COMPLETE = resolve(HERE, '__fixtures__/complete');
const INCOMPLETE = resolve(HERE, '__fixtures__/incomplete');

test('matchGlob treats ** as zero-or-more directories', () => {
  assert.equal(matchGlob('evals/fixtures/a.json', 'evals/fixtures/**/*.json'), true);
  assert.equal(matchGlob('evals/fixtures/nested/a.json', 'evals/fixtures/**/*.json'), true);
  assert.equal(matchGlob('evals/other/a.json', 'evals/fixtures/**/*.json'), false);
});

test('validateHarnessFixture enforces lifecycle and durable cites', () => {
  const ok = validateHarnessFixture(
    {
      fixture_id: 'x',
      customer_id: 'c',
      session_id: 's',
      message: 'm',
      metadata: { lifecycle: 'judge_dev', cites: ['F1', 'T2'] },
    },
    { requireLifecycle: true, requireCites: true },
  );
  assert.equal(ok.passed, true);

  const bad = validateHarnessFixture(
    {
      fixture_id: 'x',
      customer_id: 'c',
      session_id: 's',
      message: 'm',
      metadata: { lifecycle: 'nope', cites: ['G1'] },
    },
    { requireLifecycle: true, requireCites: true },
  );
  assert.equal(bad.passed, false);
  assert.ok([...HARNESS_LIFECYCLES].length === 4);
});

test('complete fixture harness passes all deterministic chapter checks', () => {
  const result = runDeterministicCheck({
    githubActor: 'fixture-complete',
    chapterRaw: 'all chapters',
    learnerRepoDir: COMPLETE,
  });
  assert.equal(result.passedCount, result.total);
  assert.ok(result.aiEligibleChapters.length > 0);
});

test('incomplete fixture harness fails setup gitignore and later chapters', () => {
  const result = runDeterministicCheck({
    githubActor: 'fixture-incomplete',
    chapterRaw: 'all chapters',
    learnerRepoDir: INCOMPLETE,
  });
  assert.ok(result.passedCount < result.total);
  const setup = result.context.rows.find((r) => r.chapter === 'setup');
  assert.equal(setup.deterministicPassed, false);
});

test('single-chapter progress check scopes to one row and never marks AI eligible', () => {
  const result = runDeterministicCheck({
    githubActor: 'fixture-complete',
    chapterRaw: '2.2',
    learnerRepoDir: COMPLETE,
  });
  assert.equal(result.total, 1);
  assert.equal(result.context.rows[0].chapter, '2.2');
  assert.deepEqual(result.aiEligibleChapters, []);
});
