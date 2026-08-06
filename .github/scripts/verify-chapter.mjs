/**
 * Per-chapter scorecard attribution (pure) — Cursor Forge verify-lesson analogue.
 */

import { evaluateChapterDeterministic } from './verify-completion-evidence.mjs';
import { normalizeChapterInput } from './chapter-registry.mjs';

export function selectAiEligibleChapters(scope, { harnessRoot, chapterId } = {}) {
  // Mid-course progress checks never spend an AI call.
  if (chapterId) return [];
  return scope.filter(
    (d) => d.checks?.ai && evaluateChapterDeterministic(d, harnessRoot).passed,
  );
}

export function evaluateChapterRow(descriptor, harnessRoot) {
  const deterministic = evaluateChapterDeterministic(descriptor, harnessRoot);
  return {
    chapter: descriptor.chapter,
    title: descriptor.title,
    deterministicPassed: deterministic.passed,
    deterministicReasons: deterministic.reasons,
    deterministicChecklist: deterministic.checklist,
    aiDeclared: !!descriptor.checks?.ai,
  };
}

/**
 * Combine deterministic rows + AI criteria into a final scorecard.
 * AI criteria shape: [{ chapter, id, description, passed, confidence }]
 */
export function evaluateModuleCompletionReview(criteriaForChapter) {
  if (!criteriaForChapter || criteriaForChapter.length === 0) {
    return { passed: false, reason: 'No AI criteria returned for this chapter.' };
  }
  for (const item of criteriaForChapter) {
    if (item.passed === false || item.confidence === 'low') {
      return {
        passed: false,
        reason: item.reason ?? `Criterion "${item.id ?? item.description}" failed or low confidence.`,
      };
    }
  }
  return { passed: true, reason: null };
}

export function mergeAiIntoRows(rows, criteria = []) {
  const byChapter = new Map();
  for (const item of criteria) {
    const key = item.chapter;
    if (!key) continue;
    if (!byChapter.has(key)) byChapter.set(key, []);
    byChapter.get(key).push(item);
  }

  return rows.map((row) => {
    if (!row.aiDeclared) {
      return { ...row, aiStatus: 'n/a', aiPassed: null, aiReason: null, ok: row.deterministicPassed };
    }
    if (!row.deterministicPassed) {
      return {
        ...row,
        aiStatus: 'skipped',
        aiPassed: null,
        aiReason: 'Deterministic checks still red — AI review not run.',
        ok: false,
      };
    }
    const chapterCriteria = byChapter.get(row.chapter);
    if (!chapterCriteria) {
      return {
        ...row,
        aiStatus: 'missing',
        aiPassed: false,
        aiReason: 'AI review did not return criteria for this chapter.',
        ok: false,
      };
    }
    const review = evaluateModuleCompletionReview(chapterCriteria);
    return {
      ...row,
      aiStatus: review.passed ? 'pass' : 'flagged',
      aiPassed: review.passed,
      aiReason: review.reason,
      ok: row.deterministicPassed && review.passed,
    };
  });
}

export function decideCertification(rows, { chapterId } = {}) {
  if (chapterId) {
    return {
      certify: false,
      reason: 'Single-chapter progress checks never certify.',
    };
  }
  const failed = rows.filter((r) => r.ok === false || (r.ok === undefined && !r.deterministicPassed));
  if (failed.length > 0) {
    return {
      certify: false,
      reason: `Not all chapters passed (${failed.map((r) => r.chapter).join(', ')}).`,
    };
  }
  const aiFlagged = rows.some((r) => r.aiStatus === 'flagged');
  if (aiFlagged) {
    return {
      certify: true,
      pendingReview: true,
      reason: 'Deterministic checks passed; AI review flagged for admin review.',
    };
  }
  return { certify: true, pendingReview: false, reason: null };
}

export function renderScorecardMarkdown({ displayName, githubActor, chapterId, rows, decision }) {
  const scope = chapterId ? `chapter \`${chapterId}\`` : 'all chapters';
  const lines = [
    `# Completion scorecard — ${scope}`,
    '',
    `**Learner:** ${displayName || githubActor} (@${githubActor})`,
    '',
    '| Chapter | Deterministic | AI | OK |',
    '| --- | --- | --- | --- |',
  ];

  for (const row of rows) {
    const det = row.deterministicPassed ? 'Pass' : 'Fail';
    const ai =
      row.aiStatus === 'n/a'
        ? 'n/a'
        : row.aiStatus === 'skipped'
          ? 'skipped'
          : row.aiStatus === 'pass'
            ? 'Pass'
            : row.aiStatus === 'flagged'
              ? 'Flagged'
              : row.aiDeclared
                ? '—'
                : 'n/a';
    const ok = row.ok === true ? 'yes' : row.ok === false ? 'no' : row.deterministicPassed ? 'yes*' : 'no';
    lines.push(`| ${row.chapter} ${row.title} | ${det} | ${ai} | ${ok} |`);
  }

  lines.push('');
  lines.push(
    '> Deterministic checks cover files, shapes, and counts only. They cannot tell human judgement from agent-authored prose that satisfies the same schema.',
  );

  const failing = rows.filter((r) => !r.deterministicPassed);
  if (failing.length) {
    lines.push('', '## Failures');
    for (const row of failing) {
      lines.push(`### ${row.chapter} — ${row.title}`);
      for (const reason of row.deterministicReasons ?? []) {
        lines.push(`- ${reason}`);
      }
    }
  }

  if (decision) {
    lines.push('', '## Certification');
    if (!decision.certify) {
      lines.push(`Not certified: ${decision.reason}`);
    } else if (decision.pendingReview) {
      lines.push(`Pending admin review: ${decision.reason}`);
    } else {
      lines.push('Ready to certify — all required checks passed.');
    }
  }

  return lines.join('\n');
}

export { normalizeChapterInput };
