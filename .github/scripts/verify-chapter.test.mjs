import assert from 'node:assert/strict';
import test from 'node:test';

import {
  decideCertification,
  evaluateModuleCompletionReview,
  mergeAiIntoRows,
} from './verify-chapter.mjs';

test('mergeAiIntoRows skips AI when deterministic failed', () => {
  const rows = mergeAiIntoRows(
    [
      {
        chapter: '1.2',
        title: 'Scoring',
        deterministicPassed: false,
        aiDeclared: true,
      },
    ],
    [{ chapter: '1.2', id: 'c1', passed: true, confidence: 'high' }],
  );
  assert.equal(rows[0].aiStatus, 'skipped');
  assert.equal(rows[0].ok, false);
});

test('evaluateModuleCompletionReview fails closed on low confidence', () => {
  const review = evaluateModuleCompletionReview([
    { id: 'c1', passed: true, confidence: 'low' },
  ]);
  assert.equal(review.passed, false);
});

test('decideCertification never certifies single-chapter runs', () => {
  const decision = decideCertification([{ ok: true }], { chapterId: '2.2' });
  assert.equal(decision.certify, false);
});

test('decideCertification requires all chapters ok for full run', () => {
  const decision = decideCertification(
    [
      { ok: true },
      { ok: false },
    ],
    { chapterId: null },
  );
  assert.equal(decision.certify, false);
});
