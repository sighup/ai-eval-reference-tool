#!/usr/bin/env node
/**
 * Derives a learner's harness fork name from their GitHub handle.
 *
 * Inputs (CLI mode):
 *   GITHUB_ACTOR   Dispatching handle
 *
 * Prints the derived repo name on stdout so workflows can capture it.
 */

import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { requireEnv } from './github-client.mjs';

export const HARNESS_REPO_PREFIX = 'ai-eval-harness-';

export function deriveHarnessRepoName(githubActor) {
  const sanitized = String(githubActor ?? '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '');

  if (!sanitized) {
    throw new Error(
      `Cannot derive a harness repo name from actor: ${JSON.stringify(githubActor ?? '')}`,
    );
  }

  return `${HARNESS_REPO_PREFIX}${sanitized}`;
}

function main() {
  const githubActor = requireEnv('GITHUB_ACTOR', process.env.GITHUB_ACTOR);
  console.log(deriveHarnessRepoName(githubActor));
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1]);

if (isMain) {
  try {
    main();
  } catch (err) {
    console.error(`Could not derive learner fork name: ${err.message ?? String(err)}`);
    process.exit(1);
  }
}
