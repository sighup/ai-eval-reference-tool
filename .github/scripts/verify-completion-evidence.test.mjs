import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, cpSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import {
  matchGlob,
  validateHarnessFixture,
  HARNESS_LIFECYCLES,
  evaluateAuditRecords,
  evaluateScorerConfig,
  evaluateAttackResults,
  evaluateGitignoreKeepsStarterTraces,
  evaluateChapterDeterministic,
  isPresentFile,
} from './verify-completion-evidence.mjs';
import { runDeterministicCheck } from './check-deterministic.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const COMPLETE = resolve(HERE, '__fixtures__/complete');
const INCOMPLETE = resolve(HERE, '__fixtures__/incomplete');

test('matchGlob treats ** as zero-or-more directories', () => {
  assert.equal(matchGlob('evals/fixtures/a.json', 'evals/fixtures/**/*.json'), true);
  assert.equal(matchGlob('evals/fixtures/nested/a.json', 'evals/fixtures/**/*.json'), true);
  assert.equal(matchGlob('evals/fixtures/sub/deep/a.json', 'evals/fixtures/**/*.json'), true);
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

test('single-chapter progress check scopes to one row', () => {
  const result = runDeterministicCheck({
    githubActor: 'fixture-complete',
    chapterRaw: '2.2',
    learnerRepoDir: COMPLETE,
  });
  assert.equal(result.total, 1);
  assert.equal(result.context.rows[0].chapter, '2.2');
});

test('evaluateAuditRecords ignores unrelated JSON when a valid AuditRecord exists', () => {
  const tmp = mkdtempSync(join(tmpdir(), 'audit-extra-'));
  try {
    cpSync(COMPLETE, tmp, { recursive: true });
    const outDir = join(tmp, 'evals', 'out');
    mkdirSync(outDir, { recursive: true });
    writeFileSync(join(outDir, 'unrelated.json'), JSON.stringify({ hello: 'world' }));
    const result = evaluateAuditRecords(tmp, {
      globs: ['evals/out/**/*.json'],
      minCount: 1,
    });
    assert.equal(result.passed, true);
    assert.ok(result.validCount >= 1);
    assert.equal(result.reasons.length, 0);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test('evaluateScorerConfig prefers a valid alternate over a scaffold', () => {
  const tmp = mkdtempSync(join(tmpdir(), 'scorer-shadow-'));
  try {
    mkdirSync(join(tmp, 'evals', 'harness'), { recursive: true });
    mkdirSync(join(tmp, 'evals'), { recursive: true });
    writeFileSync(join(tmp, 'evals', 'harness', 'scorer_config.json'), JSON.stringify({ deterministic: [] }));
    writeFileSync(
      join(tmp, 'evals', 'scorer_config.json'),
      JSON.stringify({ deterministic: ['schema_validity'], judge: ['field_faithfulness'] }),
    );
    const result = evaluateScorerConfig(tmp, {
      globs: ['evals/harness/scorer_config.json', 'evals/scorer_config.json'],
      requiredDeterministic: ['schema_validity'],
      requireJudgeNonEmpty: true,
    });
    assert.equal(result.passed, true);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test('evaluateAuditRecords fails closed on invalid JSON and ignores null payloads', () => {
  const tmp = mkdtempSync(join(tmpdir(), 'audit-null-'));
  try {
    const outDir = join(tmp, 'evals', 'out');
    mkdirSync(outDir, { recursive: true });
    writeFileSync(join(outDir, 'bad.json'), '{not-json');
    writeFileSync(join(outDir, 'null.json'), 'null');
    writeFileSync(
      join(outDir, 'good.json'),
      JSON.stringify({ audit_record_version: 1, fixtures: [] }),
    );
    const withGood = evaluateAuditRecords(tmp, { globs: ['evals/out/**/*.json'], minCount: 1 });
    assert.equal(withGood.passed, true);
    assert.ok(withGood.reasons.some((r) => r.includes('not valid JSON')));

    rmSync(join(outDir, 'good.json'));
    const onlyBad = evaluateAuditRecords(tmp, { globs: ['evals/out/**/*.json'], minCount: 1 });
    assert.equal(onlyBad.passed, false);
    assert.ok(onlyBad.reasons.some((r) => r.includes('not valid JSON')));
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test('evaluateGitignoreKeepsStarterTraces accepts root-anchored negation', () => {
  const tmp = mkdtempSync(join(tmpdir(), 'gitignore-'));
  try {
    writeFileSync(join(tmp, '.gitignore'), '.env\ntraces/*\n!/traces/starter/\n');
    const result = evaluateGitignoreKeepsStarterTraces(tmp);
    assert.equal(result.passed, true);

    writeFileSync(join(tmp, '.gitignore'), '.env\n# !traces/starter/\ntraces/*\n');
    const commented = evaluateGitignoreKeepsStarterTraces(tmp);
    assert.equal(commented.passed, false);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test('filesPresentAny rejects empty directories', () => {
  const tmp = mkdtempSync(join(tmpdir(), 'files-any-'));
  try {
    mkdirSync(join(tmp, 'evals', 'judge'), { recursive: true });
    assert.equal(isPresentFile(tmp, 'evals/judge'), false);
    const result = evaluateChapterDeterministic(
      {
        checks: {
          deterministic: {
            filesPresentAny: ['evals/judge', 'evals/judge/README.md'],
          },
        },
      },
      tmp,
    );
    assert.equal(result.passed, false);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test('unknown deterministic keys fail the chapter', () => {
  const result = evaluateChapterDeterministic(
    { checks: { deterministic: { filePresentAny: ['x.md'] } } },
    process.cwd(),
  );
  assert.equal(result.passed, false);
  assert.ok(result.reasons.some((r) => r.includes('filePresentAny')));
});

test('evaluateAttackResults reports one malformed-line reason with line number', () => {
  const tmp = mkdtempSync(join(tmpdir(), 'attacks-'));
  try {
    mkdirSync(join(tmp, 'evals', 'red-team'), { recursive: true });
    writeFileSync(
      join(tmp, 'evals', 'red-team', 'attacks.jsonl'),
      [
        JSON.stringify({ target: 'sut' }),
        'not-json',
        'also-bad',
        JSON.stringify({ target: 'sut' }),
        JSON.stringify({ target: 'judge' }),
      ].join('\n'),
    );
    const result = evaluateAttackResults(tmp, {
      globs: ['evals/red-team/attacks.jsonl'],
      minSut: 2,
      minJudge: 1,
    });
    assert.equal(result.passed, false);
    const malformed = result.reasons.filter((r) => r.includes('non-JSON'));
    assert.equal(malformed.length, 1);
    assert.ok(malformed[0].includes('line 2'));
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});
