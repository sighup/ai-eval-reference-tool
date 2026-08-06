/**
 * Chapter verification registry loader and scope helpers.
 * Analogue of cursor-forge verify-lesson.mjs's registry + scope functions.
 */

import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const DEFAULT_REGISTRY_PATH = resolve(
  REPO_ROOT,
  '.github/completion/chapter-verification.json',
);

/** workflow_dispatch sentinel for a full-course run */
export const FULL_COURSE_INPUT = 'all chapters';

export function loadChapterDescriptors(path = DEFAULT_REGISTRY_PATH) {
  if (!existsSync(path)) {
    throw new Error(`Chapter verification registry not found: ${path}`);
  }
  const data = JSON.parse(readFileSync(path, 'utf8'));
  const chapters = data?.chapters;
  if (!Array.isArray(chapters) || chapters.length === 0) {
    throw new Error(`Invalid chapter registry: expected a non-empty "chapters" array in ${path}`);
  }

  const seen = new Set();
  for (const [index, descriptor] of chapters.entries()) {
    const chapter = descriptor?.chapter;
    if (!chapter || typeof chapter !== 'string') {
      throw new Error(`Invalid chapter descriptor at index ${index} in ${path}: "chapter" is required.`);
    }
    if (seen.has(chapter)) {
      throw new Error(`Invalid chapter registry: duplicate chapter "${chapter}" in ${path}.`);
    }
    seen.add(chapter);

    if (!descriptor?.title?.trim()) {
      throw new Error(`Invalid chapter descriptor "${chapter}" in ${path}: "title" is required.`);
    }
    if (!Array.isArray(descriptor?.courseSections) || descriptor.courseSections.length === 0) {
      throw new Error(
        `Invalid chapter descriptor "${chapter}" in ${path}: "courseSections" must be a non-empty array.`,
      );
    }
    const checks = descriptor?.checks;
    if (!checks || (checks.deterministic === undefined && checks.ai === undefined && checks.precondition === undefined)) {
      throw new Error(
        `Invalid chapter descriptor "${chapter}" in ${path}: "checks" must declare at least one check.`,
      );
    }
  }

  return chapters;
}

export function normalizeChapterInput(raw) {
  const trimmed = raw?.trim();
  if (!trimmed || trimmed === FULL_COURSE_INPUT) return null;
  return trimmed;
}

export function resolveChapterScope(descriptors, chapterId) {
  if (!chapterId) return descriptors;
  const match = descriptors.find((d) => d.chapter === chapterId);
  if (!match) {
    throw new Error(
      `Unknown chapter "${chapterId}". Expected one of: ${descriptors.map((d) => d.chapter).join(', ')}.`,
    );
  }
  return [match];
}

export function expectedChapterIds(descriptors = loadChapterDescriptors()) {
  return descriptors.map((d) => d.chapter);
}
