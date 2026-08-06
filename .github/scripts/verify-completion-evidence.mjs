/**
 * Deterministic evidence collectors and pure evaluators for learner harnesses.
 *
 * Operates on a local harness root (cloned forge fork or fixture tree).
 * Does not talk to Jira/Sentry/Neon — those are Cursor Forge-specific.
 */

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

export const HARNESS_LIFECYCLES = new Set([
  'judge_dev',
  'calibration_holdout',
  'drift_regression',
  'regression',
]);

export const DURABLE_CITE_RE = /^(F|T)\d+$/;

const GENERATOR_FIELDS = ['fixture_id', 'customer_id', 'session_id', 'message'];

export function checklistItem(label, passed, detail = null) {
  return { label, passed: !!passed, ...(detail ? { detail } : {}) };
}

function walkFiles(root, { match } = {}) {
  const out = [];
  if (!existsSync(root)) return out;

  const stack = [root];
  while (stack.length) {
    const dir = stack.pop();
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules' || entry.name === '.git' || entry.name === '.venv') continue;
        stack.push(full);
      } else if (entry.isFile()) {
        const rel = relative(root, full).split('\\').join('/');
        if (!match || match(rel, full)) out.push(rel);
      }
    }
  }
  return out.sort();
}

/** Minimal glob: supports `**` (any depth, including zero) and `*`. */
export function matchGlob(path, glob) {
  const normalized = path.split('\\').join('/');
  const pattern = glob
    .split('\\')
    .join('/')
    .replace(/[.+^${}()|[\]\\]/g, '\\$&')
    // `**/` may match zero directories so `dir/**/*.json` includes `dir/file.json`.
    .replace(/\*\*\//g, '(?:.*/)?')
    .replace(/\*\*/g, '.*')
    .replace(/\*/g, '[^/]*');
  return new RegExp(`^${pattern}$`).test(normalized);
}

export function expandGlobs(harnessRoot, globs = []) {
  const allFiles = walkFiles(harnessRoot);
  const matched = new Set();
  for (const glob of globs) {
    for (const file of allFiles) {
      if (matchGlob(file, glob)) matched.add(file);
    }
  }
  return [...matched].sort();
}

export function pathExists(harnessRoot, relPath) {
  return existsSync(join(harnessRoot, relPath));
}

export function readText(harnessRoot, relPath) {
  return readFileSync(join(harnessRoot, relPath), 'utf8');
}

export function readJson(harnessRoot, relPath) {
  return JSON.parse(readText(harnessRoot, relPath));
}

export function collectManifestOverrides(harnessRoot) {
  const manifestPath = 'evals/scorecard-manifest.json';
  if (!pathExists(harnessRoot, manifestPath)) return null;
  try {
    return readJson(harnessRoot, manifestPath);
  } catch (err) {
    return { __error: `evals/scorecard-manifest.json is not valid JSON: ${err.message}` };
  }
}

export function validateHarnessFixture(payload, { requireLifecycle = true, requireCites = true } = {}) {
  const reasons = [];
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return { passed: false, reasons: ['fixture is not a JSON object'] };
  }

  for (const field of GENERATOR_FIELDS) {
    const value = payload[field];
    if (typeof value !== 'string' || !value.trim()) {
      reasons.push(`missing or empty generator field "${field}"`);
    }
  }

  if (payload.prompt?.system) {
    reasons.push('fixture must not store prompt.system (render from templates at run time)');
  }

  const metadata = payload.metadata ?? {};
  if (requireLifecycle) {
    if (!HARNESS_LIFECYCLES.has(metadata.lifecycle)) {
      reasons.push(
        `metadata.lifecycle must be one of ${[...HARNESS_LIFECYCLES].join(', ')} (got ${JSON.stringify(metadata.lifecycle)})`,
      );
    }
  }

  if (requireCites) {
    const cites = metadata.cites;
    if (!Array.isArray(cites) || cites.length === 0) {
      reasons.push('metadata.cites must be a non-empty array of durable F*/T* ids');
    } else {
      for (const cite of cites) {
        if (typeof cite !== 'string' || !DURABLE_CITE_RE.test(cite)) {
          reasons.push(`invalid cite ${JSON.stringify(cite)} (expected F* or T* only)`);
        }
      }
    }
  }

  return { passed: reasons.length === 0, reasons };
}

export function evaluateHarnessFixtures(harnessRoot, config = {}) {
  const globs = config.globs ?? ['evals/fixtures/**/*.json'];
  const files = expandGlobs(harnessRoot, globs);
  const reasons = [];
  const checklist = [];
  const byId = new Map();

  const minCount = config.minCount ?? 0;
  const labelCount = `At least ${minCount} harness fixture(s) under ${globs.join(', ')}`;
  if (files.length < minCount) {
    reasons.push(`Found ${files.length} harness fixture(s); need at least ${minCount}.`);
    checklist.push(checklistItem(labelCount, false, `found ${files.length}.`));
  } else {
    checklist.push(checklistItem(labelCount, true));
  }

  for (const file of files) {
    let payload;
    try {
      payload = readJson(harnessRoot, file);
    } catch (err) {
      reasons.push(`\`${file}\` is not valid JSON: ${err.message}`);
      checklist.push(checklistItem(`\`${file}\` is valid harness fixture JSON`, false, err.message));
      continue;
    }

    const result = validateHarnessFixture(payload, {
      requireLifecycle: config.requireLifecycle !== false,
      requireCites: !!config.requireCites,
    });
    if (!result.passed) {
      for (const reason of result.reasons) {
        reasons.push(`\`${file}\`: ${reason}`);
      }
      checklist.push(
        checklistItem(`\`${file}\` passes harness fixture contract`, false, result.reasons.join('; ')),
      );
    } else {
      checklist.push(checklistItem(`\`${file}\` passes harness fixture contract`, true));
    }

    const id = payload?.fixture_id;
    if (typeof id === 'string' && id.trim()) {
      const lifecycle = payload?.metadata?.lifecycle;
      if (!byId.has(id)) byId.set(id, []);
      byId.get(id).push({ file, lifecycle });
    }
  }

  if (config.requireLifecycleDisjoint) {
    for (const [id, entries] of byId.entries()) {
      const lifecycles = new Set(entries.map((e) => e.lifecycle).filter(Boolean));
      if (lifecycles.size > 1) {
        const detail = entries.map((e) => `${e.file}=${e.lifecycle}`).join(', ');
        reasons.push(`fixture_id "${id}" appears under multiple lifecycles: ${detail}`);
        checklist.push(
          checklistItem(`fixture_id \`${id}\` has a single lifecycle`, false, detail),
        );
      }
    }
  }

  return { passed: reasons.length === 0, reasons, checklist, files };
}

export function evaluateScorerConfig(harnessRoot, config = {}) {
  const globs = config.globs ?? ['evals/harness/scorer_config.json'];
  const files = expandGlobs(harnessRoot, globs);
  const reasons = [];
  const checklist = [];

  if (files.length === 0) {
    reasons.push(`No scorer_config.json found (looked for ${globs.join(', ')}).`);
    checklist.push(checklistItem('scorer_config.json is present', false, 'not found.'));
    return { passed: false, reasons, checklist };
  }

  const file = files[0];
  let payload;
  try {
    payload = readJson(harnessRoot, file);
  } catch (err) {
    reasons.push(`\`${file}\` is not valid JSON: ${err.message}`);
    checklist.push(checklistItem(`\`${file}\` is valid JSON`, false, err.message));
    return { passed: false, reasons, checklist };
  }

  checklist.push(checklistItem(`\`${file}\` is present`, true));

  if (!Array.isArray(payload.deterministic)) {
    reasons.push(`\`${file}\`: "deterministic" must be an array.`);
    checklist.push(checklistItem(`\`${file}\` has deterministic scorer list`, false));
  } else {
    checklist.push(checklistItem(`\`${file}\` has deterministic scorer list`, true));
    for (const id of config.requiredDeterministic ?? []) {
      const present = payload.deterministic.includes(id);
      const label = `\`${file}\` lists deterministic scorer \`${id}\``;
      if (!present) {
        reasons.push(`\`${file}\` is missing deterministic scorer "${id}".`);
        checklist.push(checklistItem(label, false, 'missing.'));
      } else {
        checklist.push(checklistItem(label, true));
      }
    }
  }

  if (config.requireJudgeNonEmpty) {
    const ok = Array.isArray(payload.judge) && payload.judge.length > 0;
    const label = `\`${file}\` has a non-empty judge list`;
    if (!ok) {
      reasons.push(`\`${file}\`: "judge" must be a non-empty array once Chapter 3 starts.`);
      checklist.push(checklistItem(label, false));
    } else {
      checklist.push(checklistItem(label, true));
    }
  } else if (payload.judge !== undefined && !Array.isArray(payload.judge)) {
    reasons.push(`\`${file}\`: "judge" must be an array when present.`);
    checklist.push(checklistItem(`\`${file}\` judge field is an array`, false));
  }

  return { passed: reasons.length === 0, reasons, checklist };
}

export function evaluateAuditRecords(harnessRoot, config = {}) {
  const globs = config.globs ?? ['evals/out/**/*.json'];
  const files = expandGlobs(harnessRoot, globs);
  const reasons = [];
  const checklist = [];
  const minCount = config.minCount ?? 1;

  let validCount = 0;
  for (const file of files) {
    let payload;
    try {
      payload = readJson(harnessRoot, file);
    } catch (err) {
      checklist.push(
        checklistItem(`\`${file}\` skipped (not valid JSON)`, false, err.message),
      );
      continue;
    }
    const okVersion = payload.audit_record_version === 1 || payload.audit_record_version === '1';
    const okFixtures = Array.isArray(payload.fixtures);
    if (okVersion && okFixtures) {
      validCount += 1;
      checklist.push(checklistItem(`\`${file}\` looks like an AuditRecord`, true));
    } else {
      checklist.push(
        checklistItem(
          `\`${file}\` skipped (not an AuditRecord envelope)`,
          true,
          'missing audit_record_version=1 and/or fixtures[]; ignored for minCount',
        ),
      );
    }
  }

  const labelCount = `At least ${minCount} valid AuditRecord(s) under ${globs.join(', ')}`;
  if (validCount < minCount) {
    reasons.push(
      `Found ${validCount} valid AuditRecord(s); need at least ${minCount}.`,
    );
    checklist.push(checklistItem(labelCount, false, `found ${validCount}.`));
  } else {
    checklist.push(checklistItem(labelCount, true));
  }

  return { passed: validCount >= minCount, reasons, checklist, validCount };
}

export function evaluateCalibrationRecords(harnessRoot, config = {}) {
  const globs = config.globs ?? ['evals/calibration/record.json'];
  const files = expandGlobs(harnessRoot, globs);
  const reasons = [];
  const checklist = [];
  const minCount = config.minCount ?? 1;
  const requiredKeys = ['component', 'judge_config', 'scorers'];

  if (files.length < minCount) {
    reasons.push(`Found ${files.length} calibration record(s); need at least ${minCount}.`);
    checklist.push(checklistItem(`At least ${minCount} calibration record(s)`, false, `found ${files.length}.`));
    return { passed: false, reasons, checklist };
  }

  for (const file of files) {
    let payload;
    try {
      payload = readJson(harnessRoot, file);
    } catch (err) {
      reasons.push(`\`${file}\` is not valid JSON: ${err.message}`);
      checklist.push(checklistItem(`\`${file}\` is valid JSON`, false, err.message));
      continue;
    }
    const missing = requiredKeys.filter((key) => payload[key] === undefined);
    if (missing.length) {
      reasons.push(`\`${file}\` missing keys: ${missing.join(', ')}`);
      checklist.push(checklistItem(`\`${file}\` has required calibration keys`, false, missing.join(', ')));
    } else {
      checklist.push(checklistItem(`\`${file}\` has required calibration keys`, true));
    }
  }

  return { passed: reasons.length === 0, reasons, checklist };
}

export function evaluateAttackResults(harnessRoot, config = {}) {
  const globs = config.globs ?? ['evals/red-team/attacks.jsonl'];
  const files = expandGlobs(harnessRoot, globs);
  const reasons = [];
  const checklist = [];
  const minSut = config.minSut ?? 0;
  const minJudge = config.minJudge ?? 0;

  if (files.length === 0) {
    reasons.push(`No attacks.jsonl found (looked for ${globs.join(', ')}).`);
    checklist.push(checklistItem('attacks.jsonl is present', false, 'not found.'));
    return { passed: false, reasons, checklist };
  }

  let sut = 0;
  let judge = 0;
  for (const file of files) {
    const lines = readText(harnessRoot, file)
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean);
    for (const line of lines) {
      let row;
      try {
        row = JSON.parse(line);
      } catch {
        reasons.push(`\`${file}\` contains a non-JSON line.`);
        continue;
      }
      if (row.target === 'sut') sut += 1;
      if (row.target === 'judge') judge += 1;
    }
  }

  const sutLabel = `At least ${minSut} SUT attack result(s)`;
  if (sut < minSut) {
    reasons.push(`Found ${sut} SUT attack(s); need at least ${minSut}.`);
    checklist.push(checklistItem(sutLabel, false, `found ${sut}.`));
  } else {
    checklist.push(checklistItem(sutLabel, true));
  }

  const judgeLabel = `At least ${minJudge} judge attack result(s)`;
  if (judge < minJudge) {
    reasons.push(`Found ${judge} judge attack(s); need at least ${minJudge}.`);
    checklist.push(checklistItem(judgeLabel, false, `found ${judge}.`));
  } else if (minJudge > 0) {
    checklist.push(checklistItem(judgeLabel, true));
  }

  return { passed: reasons.length === 0, reasons, checklist };
}

export function evaluateGitignoreKeepsStarterTraces(harnessRoot) {
  const reasons = [];
  const checklist = [];
  if (!pathExists(harnessRoot, '.gitignore')) {
    reasons.push('`.gitignore` is missing.');
    checklist.push(checklistItem('`.gitignore` keeps `traces/starter/`', false, 'file missing.'));
    return { passed: false, reasons, checklist };
  }
  const text = readText(harnessRoot, '.gitignore');
  const hasNegation =
    text.includes('!traces/starter/') ||
    text.includes('!./traces/starter/') ||
    /!\s*traces\/starter\//.test(text);
  if (!hasNegation) {
    reasons.push('`.gitignore` must un-ignore `traces/starter/` (load-bearing negation).');
    checklist.push(checklistItem('`.gitignore` keeps `traces/starter/`', false, 'negation missing.'));
  } else {
    checklist.push(checklistItem('`.gitignore` keeps `traces/starter/`', true));
  }
  return { passed: reasons.length === 0, reasons, checklist };
}

export function countDirectoryFiles(harnessRoot, relDir, { extension } = {}) {
  const full = join(harnessRoot, relDir);
  if (!existsSync(full) || !statSync(full).isDirectory()) return 0;
  return readdirSync(full).filter((name) => {
    if (extension && !name.endsWith(extension)) return false;
    try {
      return statSync(join(full, name)).isFile();
    } catch {
      return false;
    }
  }).length;
}

/**
 * Evaluate one chapter's `checks.deterministic` block against a harness root.
 */
export function evaluateChapterDeterministic(descriptor, harnessRoot) {
  const config = descriptor?.checks?.deterministic;
  if (!config) return { passed: true, reasons: [], checklist: [] };

  const reasons = [];
  const checklist = [];

  for (const path of config.filesPresent ?? []) {
    const present = pathExists(harnessRoot, path);
    const label = `\`${path}\` is present`;
    if (!present) {
      reasons.push(`\`${path}\` is not present.`);
      checklist.push(checklistItem(label, false, 'not present.'));
    } else {
      checklist.push(checklistItem(label, true));
    }
  }

  for (const path of config.directoriesPresent ?? []) {
    const full = join(harnessRoot, path);
    const present = existsSync(full) && statSync(full).isDirectory();
    const label = `\`${path}/\` directory is present`;
    if (!present) {
      reasons.push(`\`${path}/\` directory is not present.`);
      checklist.push(checklistItem(label, false, 'not present.'));
    } else {
      checklist.push(checklistItem(label, true));
    }
  }

  const filesPresentAny = config.filesPresentAny ?? [];
  if (filesPresentAny.length > 0) {
    const anyPresent = filesPresentAny.some((path) => pathExists(harnessRoot, path));
    const pathList = filesPresentAny.map((path) => `\`${path}\``).join(' or ');
    const label = `One of ${pathList} is present`;
    if (!anyPresent) {
      reasons.push(`None of ${pathList} is present.`);
      checklist.push(checklistItem(label, false, 'none present.'));
    } else {
      checklist.push(checklistItem(label, true));
    }
  }

  if (config.starterFixtureMinCount != null) {
    const count = countDirectoryFiles(harnessRoot, 'fixtures/starter', { extension: '.json' });
    const need = config.starterFixtureMinCount;
    const label = `At least ${need} files in \`fixtures/starter/\``;
    if (count < need) {
      reasons.push(`Found ${count} starter fixture(s); need at least ${need}.`);
      checklist.push(checklistItem(label, false, `found ${count}.`));
    } else {
      checklist.push(checklistItem(label, true));
    }
  }

  if (config.starterTraceMinCount != null) {
    const count = countDirectoryFiles(harnessRoot, 'traces/starter', { extension: '.jsonl' });
    const need = config.starterTraceMinCount;
    const label = `At least ${need} files in \`traces/starter/\``;
    if (count < need) {
      reasons.push(`Found ${count} starter trace file(s); need at least ${need}.`);
      checklist.push(checklistItem(label, false, `found ${count}.`));
    } else {
      checklist.push(checklistItem(label, true));
    }
  }

  if (config.gitignoreKeepsStarterTraces) {
    const result = evaluateGitignoreKeepsStarterTraces(harnessRoot);
    reasons.push(...result.reasons);
    checklist.push(...result.checklist);
  }

  if (config.harnessFixtures) {
    const result = evaluateHarnessFixtures(harnessRoot, config.harnessFixtures);
    reasons.push(...result.reasons);
    checklist.push(...result.checklist);
  }

  if (config.scorerConfig) {
    const result = evaluateScorerConfig(harnessRoot, config.scorerConfig);
    reasons.push(...result.reasons);
    checklist.push(...result.checklist);
  }

  if (config.auditRecords) {
    const result = evaluateAuditRecords(harnessRoot, config.auditRecords);
    reasons.push(...result.reasons);
    checklist.push(...result.checklist);
  }

  if (config.calibrationRecords) {
    const result = evaluateCalibrationRecords(harnessRoot, config.calibrationRecords);
    reasons.push(...result.reasons);
    checklist.push(...result.checklist);
  }

  if (config.attackResults) {
    const result = evaluateAttackResults(harnessRoot, config.attackResults);
    reasons.push(...result.reasons);
    checklist.push(...result.checklist);
  }

  return { passed: reasons.length === 0, reasons, checklist };
}
