#!/usr/bin/env node
/**
 * Stage-1 historical compatibility classifier.
 *
 * ONLY used when the PR BASE predates orchestration/pr-admission.mjs.
 * Loaded from a trusted, central, pinned-at-checkout default-branch Enforcer,
 * NEVER from candidate HEAD. NO task is admitted through this path.
 * Always fail closed for managed PRs or governance-policy tampering.
 */
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { parseDiffNameStatus } from './pr-admission.mjs';

const EXPECTED_REPO = 'smgkikikiki-cloud/TDR';
const MANIFEST = '.tdr/enforcer-task.json';
const SHA40 = /^[a-f0-9]{40}$/i;
const VERSION = 'tdr.enforcer.historical-audit.v1';

function protectedGovernancePath(file) {
  return file === 'AGENTS.md' || file === 'CLAUDE.md'
    || file === MANIFEST
    || file.startsWith('.tdr/')
    || file.startsWith('orchestration/')
    || file.startsWith('.github/workflows/')
    || file.startsWith('docs/portfolio/');
}
function isSensitiveDomainState(file) {
  return file === 'docs/WORK_STATE.md'
    || file === 'docs/market-track/ROADMAP.md'
    || file === 'docs/vehicle-db/VEHICLE_DB_V3.md'
    || file.startsWith('supabase/');
}
function isPresentNoFollow(file) {
  try { fs.lstatSync(file); return true; }
  catch (error) {
    if (error?.code === 'ENOENT') return false;
    throw error;
  }
}

function safeSha(sha) {
  return typeof sha === 'string' && SHA40.test(sha);
}

/**
 * Pure determination from event, verified Git diff and manifest flag.
 * ok:true NEVER means Task Packet approval or evidence of branch compliance.
 */
export function classifyHistoricalPr({ event, changes, candidateHasManifest = false }) {
  const errors = [];
  const warnings = [];
  const pr = event?.pull_request || {};
  const baseSha = pr?.base?.sha;
  const headSha = pr?.head?.sha;
  if (event?.repository?.full_name !== EXPECTED_REPO) errors.push('REPOSITORY_MISMATCH');
  if (!Number.isSafeInteger(pr?.number) || pr.number < 1)
    errors.push('PR_NUMBER_INVALID');
  if (pr?.base?.ref !== 'main') errors.push('BASE_BRANCH_NOT_MAIN');
  if (!safeSha(baseSha) || !safeSha(headSha)) errors.push('EVENT_SHA_INVALID');
  if (!Array.isArray(changes) || changes.length === 0)
    errors.push('DIFF_NOT_AVAILABLE_OR_EMPTY');
  const paths = [];
  for (const entry of Array.isArray(changes) ? changes : []) {
    if (!entry || typeof entry.kind !== 'string'
      || !['A', 'M', 'D', 'R', 'C'].includes(entry.kind)
      || !Array.isArray(entry.paths)
      || entry.paths.length !== ('RC'.includes(entry.kind) ? 2 : 1)) {
      errors.push('DIFF_ENTRY_INVALID');
      continue;
    }
    for (const file of entry.paths) {
      if (typeof file !== 'string' || !file
        || file.startsWith('/') || file.includes('\\')
        || file.includes('\0')
        || file.split('/').some(piece => piece === '..' || piece === '.' || piece === '')) {
        errors.push('DIFF_PATH_INVALID');
        continue;
      }
      paths.push(file);
    }
  }
  const uniquePaths = [...new Set(paths)].sort();
  const managed = candidateHasManifest
    || (typeof pr?.head?.ref === 'string' && pr.head.ref.startsWith('enforcer/'))
    || uniquePaths.some(file => file.startsWith('.tdr/'));
  if (managed) errors.push('HISTORICAL_MANAGED_TASK_DENIED');
  const governanceChanges = uniquePaths.filter(protectedGovernancePath);
  if (governanceChanges.length) {
    errors.push('HISTORICAL_GOVERNANCE_CHANGE_REQUIRES_MODERN_REVIEW');
    warnings.push('GOVERNANCE_PATHS_CHANGED:' + governanceChanges.join(','));
  }
  const domainChanges = uniquePaths.filter(isSensitiveDomainState);
  if (domainChanges.length)
    warnings.push('DOMAIN_STATE_OR_SCHEMA_CHANGED_NOT_ENFORCER_APPROVED:' + domainChanges.join(','));
  warnings.push('HISTORICAL_BASE_NO_ENFORCER_POLICY');
  warnings.push('UNMANAGED_PR_IS_AUDIT_ONLY_NOT_AUTHORIZED');
  return {
    ok: errors.length === 0,
    mode: 'HISTORICAL_BASE_COMPATIBILITY',
    admission: errors.length ? 'DENIED' : 'UNMANAGED_AUDIT_ONLY',
    enforcerAuthorized: false,
    source: VERSION,
    errors, warnings,
    changedFiles: uniquePaths,
    baseSha: baseSha || null,
    headSha: headSha || null,
    prNumber: pr.number || null,
  };
}

function git(repo, args, encoding = 'utf8') {
  return execFileSync('git', args, {
    cwd: repo, encoding, timeout: 15000, maxBuffer: 16 * 1024 * 1024,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
}
export function cli(args) {
  if (args.length !== 6 || args[0] !== '--event'
      || args[2] !== '--policy-root' || args[4] !== '--candidate-root')
    throw new Error('USAGE: --event FILE --policy-root BASE --candidate-root HEAD');

  const event = JSON.parse(fs.readFileSync(path.resolve(args[1]), 'utf8'));
  const base = path.resolve(args[3]);
  const head = path.resolve(args[5]);
  const baseSha = event?.pull_request?.base?.sha;
  const headSha = event?.pull_request?.head?.sha;
  if (!safeSha(baseSha) || !safeSha(headSha))
    throw new Error('INVALID_EVENT_COMMIT_SHA');
  if (git(base, ['rev-parse', 'HEAD']).trim() !== baseSha)
    throw new Error('TRUSTED_BASE_CHECKOUT_MISMATCH');
  if (git(head, ['rev-parse', 'HEAD']).trim() !== headSha)
    throw new Error('CANDIDATE_HEAD_CHECKOUT_MISMATCH');
  if (isPresentNoFollow(path.join(base, 'orchestration/pr-admission.mjs')))
    throw new Error('NOT_HISTORICAL_BASE_USE_BASE_POLICY');
  const diff = git(head, ['diff', '--name-status', '-z', '--find-renames',
    baseSha + '...' + headSha], 'buffer');
  const changes = parseDiffNameStatus(diff);
  return classifyHistoricalPr({
    event, changes,
    candidateHasManifest: isPresentNoFollow(path.join(head, MANIFEST)),
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const outcome = cli(process.argv.slice(2));
    process.stdout.write(JSON.stringify(outcome, null, 2) + '\n');
    process.exitCode = outcome.ok ? 0 : 1;
  } catch (error) {
    process.stderr.write(JSON.stringify({
      ok: false, mode: 'HISTORICAL_BASE_COMPATIBILITY',
      admission: 'DENIED', enforcerAuthorized: false,
      errors: ['HISTORICAL_INPUT_OR_GIT_FAILURE', String(error?.message ?? error)],
    }) + '\n');
    process.exitCode = 1;
  }
}
