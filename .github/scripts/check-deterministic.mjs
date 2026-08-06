#!/usr/bin/env node
/**
 * Deterministic-check runner for the `check` job.
 *
 * Inputs:
 *   GITHUB_ACTOR       Dispatching handle (for display / repo derivation)
 *   CHAPTER            workflow input (`all chapters` or a chapter id)
 *   LEARNER_REPO_DIR   Local harness root to score (fixture path or cloned fork)
 */

import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  loadChapterDescriptors,
  normalizeChapterInput,
  resolveChapterScope,
} from './chapter-registry.mjs';
import { requireEnv, writeGithubOutput, writeStepSummary } from './github-client.mjs';
import {
  evaluateChapterRow,
  mergeAiIntoRows,
  renderScorecardMarkdown,
} from './verify-chapter.mjs';

export function runDeterministicCheck({
  githubActor,
  chapterRaw,
  learnerRepoDir,
  displayName,
} = {}) {
  const descriptors = loadChapterDescriptors();
  const chapterId = normalizeChapterInput(chapterRaw);
  const scope = resolveChapterScope(descriptors, chapterId);

  const baseRows = scope.map((descriptor) => evaluateChapterRow(descriptor, learnerRepoDir));
  // Progress checks never call an AI reviewer; merge empty criteria so declared
  // AI chapters surface as aiStatus=missing / ok=false instead of a silent Pass.
  const rows = mergeAiIntoRows(baseRows, []);

  const name = displayName ?? githubActor;
  const summary = renderScorecardMarkdown({
    displayName: name,
    githubActor,
    chapterId,
    rows,
  });

  return {
    context: {
      displayName: name,
      githubActor,
      chapterId,
      rows,
      learnerRepoDir,
    },
    summary,
    passedCount: rows.filter((r) => r.deterministicPassed).length,
    total: rows.length,
  };
}

async function main() {
  const githubActor = requireEnv('GITHUB_ACTOR', process.env.GITHUB_ACTOR);
  const learnerRepoDir = resolve(requireEnv('LEARNER_REPO_DIR', process.env.LEARNER_REPO_DIR));
  const chapterRaw = process.env.CHAPTER ?? '';

  const result = runDeterministicCheck({
    githubActor,
    chapterRaw,
    learnerRepoDir,
    displayName: process.env.DISPLAY_NAME?.trim() || githubActor,
  });

  console.log(result.summary);
  await writeStepSummary(result.summary);
  await writeGithubOutput('deterministic_context', JSON.stringify(result.context));

  console.log(
    `Deterministic checks: ${result.passedCount}/${result.total} chapter(s) passed.`,
  );

  // Fail the job when any chapter fails so progress-check workflows show red.
  if (result.passedCount < result.total) {
    process.exitCode = 1;
  }
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1]);

if (isMain) {
  main().catch((err) => {
    console.error(`Deterministic check failed: ${err.message ?? String(err)}`);
    process.exit(1);
  });
}
