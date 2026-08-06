/**
 * Shared GitHub helpers for the learner progress scorecard.
 */

export function requireEnv(name, value = process.env[name]) {
  const trimmed = value?.trim();
  if (!trimmed) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return trimmed;
}

export async function writeStepSummary(lines) {
  const summaryPath = process.env.GITHUB_STEP_SUMMARY;
  const text = Array.isArray(lines) ? lines.join('\n') : String(lines ?? '');
  if (summaryPath) {
    const { appendFile } = await import('node:fs/promises');
    await appendFile(summaryPath, `${text}\n`);
  } else {
    console.log(text);
  }
}

export async function writeGithubOutput(name, value) {
  const outputPath = process.env.GITHUB_OUTPUT;
  if (!outputPath) return;
  const { appendFile } = await import('node:fs/promises');
  const { randomUUID } = await import('node:crypto');
  const delimiter = `ghadelimiter_${randomUUID()}`;
  await appendFile(outputPath, `${name}<<${delimiter}\n${value}\n${delimiter}\n`);
}
