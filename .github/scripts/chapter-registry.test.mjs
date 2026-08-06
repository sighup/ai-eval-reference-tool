import assert from 'node:assert/strict';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import {
  FULL_COURSE_INPUT,
  loadChapterDescriptors,
  normalizeChapterInput,
  resolveChapterScope,
} from './chapter-registry.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..');

test('loadChapterDescriptors loads the real registry', () => {
  const chapters = loadChapterDescriptors();
  assert.ok(chapters.length >= 10);
  assert.equal(chapters[0].chapter, 'setup');
  assert.ok(chapters.some((c) => c.chapter === 'capstone'));
});

test('normalizeChapterInput maps all-chapters sentinel to null', () => {
  assert.equal(normalizeChapterInput(FULL_COURSE_INPUT), null);
  assert.equal(normalizeChapterInput('  '), null);
  assert.equal(normalizeChapterInput('2.2'), '2.2');
});

test('resolveChapterScope filters to one chapter', () => {
  const chapters = loadChapterDescriptors(resolve(ROOT, '.github/completion/chapter-verification.json'));
  const scope = resolveChapterScope(chapters, 'setup');
  assert.equal(scope.length, 1);
  assert.equal(scope[0].chapter, 'setup');
  assert.throws(() => resolveChapterScope(chapters, '9.9'), /Unknown chapter/);
});
