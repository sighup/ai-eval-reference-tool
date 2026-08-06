import assert from 'node:assert/strict';
import test from 'node:test';

import { requireEnv } from './github-client.mjs';

test('requireEnv returns trimmed values', () => {
  assert.equal(requireEnv('X', '  hello  '), 'hello');
});

test('requireEnv rejects missing values', () => {
  assert.throws(() => requireEnv('MISSING', ''), /Missing required environment variable: MISSING/);
  assert.throws(() => requireEnv('MISSING', undefined), /Missing required environment variable: MISSING/);
  assert.throws(() => requireEnv('MISSING', '   '), /Missing required environment variable: MISSING/);
});
