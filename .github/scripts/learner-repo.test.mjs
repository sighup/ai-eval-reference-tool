import assert from 'node:assert/strict';
import test from 'node:test';

import { deriveHarnessRepoName } from './learner-repo.mjs';

test('deriveHarnessRepoName prefixes a plain handle', () => {
  assert.equal(deriveHarnessRepoName('octocat'), 'ai-eval-harness-octocat');
});

test('deriveHarnessRepoName lowercases mixed case', () => {
  assert.equal(deriveHarnessRepoName('OctoCat-42'), 'ai-eval-harness-octocat-42');
});

test('deriveHarnessRepoName sanitizes unsupported characters', () => {
  assert.equal(deriveHarnessRepoName('ada.lovelace'), 'ai-eval-harness-ada-lovelace');
  assert.equal(deriveHarnessRepoName('  spaced  handle  '), 'ai-eval-harness-spaced-handle');
  assert.equal(deriveHarnessRepoName('a_b__c'), 'ai-eval-harness-a-b-c');
  assert.equal(deriveHarnessRepoName('-leading-and-trailing-'), 'ai-eval-harness-leading-and-trailing');
});

test('deriveHarnessRepoName throws on empty or unusable input', () => {
  for (const actor of ['', '   ', '---', '!!!', null, undefined]) {
    assert.throws(
      () => deriveHarnessRepoName(actor),
      /Cannot derive a harness repo name from actor/,
    );
  }
});
