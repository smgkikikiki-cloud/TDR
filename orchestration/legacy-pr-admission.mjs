#!/usr/bin/env node
/**
 * Compatibility gate for a PR whose BASE predates Stage 1.
 * Read-only: it NEVER authorizes a task. Use ONLY from a trusted
 * centrally checked-out Enforcer (not from the PR candidate HEAD).
 */
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { parseDiffNameStatus } from './pr-admission.mjs';

const SHA40 = /^[0-9a-f]{40}$/i;
const PACKET_PATH = '.tdr/enforcer-task.json';

function isGovernancePath(p) {
  return p === 'AGENTS.md' || p === 'CLAUDE.md'
    || p === 'docs/market-track/ROADMAP.md'
    || p === 'docs/vehicle-db/VEHICLE_DB_V3.md'
    || p === 'docs/MERGE_DECISIONS.md'
    || p === 'docs/CANONICAL_INPUT.md'
    || p.startsWith('docs/portfolio/')
    || p.startsWith('orchestration/')
    || p.startsWith('.github/')
    || p === '.tdr' || p.startsWith('.tdr/')
    || p === '.env' || p.startsWith('.env.')
    || p.startsWith('supabase/migrations/');
}
function normalizedPaths(changes) {
  if (!Array.isArray(changes) || changes.length === 0)
    throw new Error('EMPTY_OR_UNVERIFIED_PR_DIFF');
  const paths = [];
  for (const change of changes) {
    if (!change || !['A', 'M', 'D', 'R', 'C'].includes(change.kind)
      || !Array.isArray(change.paths)
      || change.paths.length !== ('RC'.includes(change.kind) ? 2 : 1))
      throw new Error('UNSUPPORTED_PR_DIFF_ENTRY');
    for (const p of change.paths) {
      if (typeof p !== 'string' || !p || p.startsWith('/')
        || p.includes('\\') || p.includes('\0')
        || p.split('/').some(x => !x || x === '.' || x === '..'))
        throw new Error('UNSAFE_PR_DIFF_PATH');
      paths.push(p);
    }
  }
  return [...new Set(paths)].sort();
}

export function evaluateLegacy({ event, changes, hasPacket = false }) {
  const errors = [], warnings = [];
  const pr = event?.pull_request;
  const baseSha = pr?.base?.sha, headSha = pr?.head?.sha;
  if (event?.repository?.full_name !== 'smgkikikiki-cloud/TDR')
    errors.push('UNEXPECTED_REPOSITORY');
  if (pr?.base?.ref !== 'main')
    errors.push('UNEXPECTED_BASE_BRANCH');
  if (!SHA40.test(String(baseSha ?? '')) || !SHA40.test(String(headSha ?? '')))
    errors.push('INVALID_EVENT_COMMIT_SHA');
  if (!Number.isInteger(pr?.number) || pr.number <= 0)
    errors.push('INVALID_PR_NUMBER');
  let paths = [];
  try { paths = normalizedPaths(changes); }
  catch (err) { errors.push('PR_DIFF_UNVERIFIED:' + err.message); }

  // The PR BASE predates Stage1; there is no trusted BASE authorization plan.
  // Therefore ALL managed-task claims must be rejected, not "grandfathered".
  const managed = hasPacket
    || (typeof pr?.head?.ref === 'string' && pr.head.ref.startsWith('enforcer/'))
    || paths.some(p => p === PACKET_PATH || p.startsWith('.tdr/'));
  if (managed) errors.push('LEGACY_BASE_MANAGED_TASK_DENIED');

  // PR HEAD is untrusted, so refuse candidate attempts to rewrite rules,
  // workflow or the central checker under this historical-base exception.
  // Domain execution state (docs/WORK_STATE.md) is intentionally NOT on this
  // governance list: legacy workstream PRs still need their OWN review gate.
  for (const p of paths.filter(isGovernancePath))
    errors.push('LEGACY_BASE_GOVERNANCE_CHANGE_DENIED:' + p);

  if (!errors.length)
    warnings.push('HISTORICAL_BASE_NO_STAGE1_POLICY_AUDIT_ONLY');
  return {
    ok: errors.length === 0,
    admission: errors.length ? 'DENIED' : 'LEGACY_UNMANAGED_AUDIT_ONLY',
    enforcerAuthorized: false,
    errors, warnings, changedFiles: paths,
    baseSha: baseSha ?? null, headSha: headSha ?? null,
    prNumber: pr?.number ?? null,
  };
}
function git(repo, args, encoding = 'utf8') {
  return execFileSync('git', args, { cwd: repo, encoding, timeout: 15000,
    maxBuffer: 16 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] });
}
export function cli(argv) {
  if (argv.length !== 6 || argv[0] !== '--event'
    || argv[2] !== '--policy-root' || argv[4] !== '--candidate-root')
    throw new Error('USAGE: --event <event.json> --policy-root <base> --candidate-root <head>');
  const event = JSON.parse(fs.readFileSync(path.resolve(argv[1]), 'utf8'));
  const policy = path.resolve(argv[3]), candidate = path.resolve(argv[5]);
  const base = event?.pull_request?.base?.sha, head = event?.pull_request?.head?.sha;
  if (!SHA40.test(String(base ?? '')) || !SHA40.test(String(head ?? '')))
    throw new Error('INVALID_GITHUB_PR_EVENT_SHA');
  if (git(policy, ['rev-parse', 'HEAD']).trim() !== base)
    throw new Error('POLICY_NOT_CHECKED_OUT_AT_EVENT_BASE');
  if (git(candidate, ['rev-parse', 'HEAD']).trim() !== head)
    throw new Error('CANDIDATE_NOT_CHECKED_OUT_AT_EVENT_HEAD');
  // No downgrade to audit-only when the BASE has a real Stage1 checker.
  if (fs.existsSync(path.join(policy, 'orchestration/pr-admission.mjs')))
    throw new Error('MODERN_BASE_MUST_USE_TRUSTED_BASE_CHECKER');
  const diff = git(candidate, ['diff', '--name-status', '-z', '--find-renames',
    base + '...' + head], 'buffer');
  const changes = parseDiffNameStatus(diff);
  const packet = path.join(candidate, PACKET_PATH);
  const hasPacket = fs.existsSync(packet) || fs.existsSync(path.dirname(packet))
    && fs.readdirSync(path.dirname(packet)).includes(path.basename(packet));
  return evaluateLegacy({ event, changes, hasPacket });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const result = cli(process.argv.slice(2));
    process.stdout.write(JSON.stringify(result, null, 2) + '\n');
    process.exitCode = result.ok ? 0 : 1;
  } catch (err) {
    process.stderr.write(JSON.stringify({ ok: false, admission: 'DENIED',
      enforcerAuthorized: false,
      errors: ['LEGACY_ADMISSION_INPUT_ERROR', String(err?.message || err)] }) + '\n');
    process.exitCode = 1;
  }
}
