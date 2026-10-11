#!/usr/bin/env node
/**
 * TDR Enforcer Stage 0: deterministic, READ-ONLY admission / repository contract check.
 *
 * NO worker dispatch, network, DB connection, GitHub writes, retries, timers, or paid APIs.
 * A valid README or an agent assertion that it read a roadmap is not an authorization.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

export const ROADMAP_FILE = 'docs/portfolio/TDR_MASTER_ROADMAP_V1.md';
export const PLAN_FILE = 'docs/portfolio/portfolio.plan.json';
const REPO_INSTRUCTIONS = ['AGENTS.md', 'CLAUDE.md'];
const POLICY_FILES = new Set([
  'AGENTS.md', 'CLAUDE.md', PLAN_FILE, ROADMAP_FILE, 'docs/WORK_STATE.md',
  'docs/market-track/ROADMAP.md', 'docs/vehicle-db/VEHICLE_DB_V3.md',
]);
const HEX40 = /^[0-9a-f]{40}$/i;
const HEX64 = /^[0-9a-f]{64}$/i;

export function digest(content) {
  return crypto.createHash('sha256').update(content, 'utf8').digest('hex');
}

export function checkRepository({ plan, roadmap, agents, claude }) {
  const errors = [];
  if (plan?.schema !== 'tdr.portfolio.approved-roadmap.v1.0')
    errors.push('PLAN_SCHEMA_UNEXPECTED');
  if (plan?.approval?.roadmap_version !== '1.0'
      || plan?.approval?.status !== 'OWNER_APPROVED')
    errors.push('ROADMAP_OWNER_APPROVAL_MISSING');
  if (plan?.roadmap_authoritative_file !== ROADMAP_FILE)
    errors.push('ROADMAP_CANONICAL_PATH_MISMATCH');
  if (!String(roadmap ?? '').startsWith('# TDR Master Development Roadmap v1.0'))
    errors.push('ROADMAP_CONTENT_MISSING_OR_WRONG_VERSION');

  // Stage-0 operation is intentionally permanently OFF. Enabling future
  // dispatch requires a separately reviewed enforcer release, never a task flag.
  if (plan?.execution?.enabled !== false)
    errors.push('UNEXPECTED_ENFORCER_ACTIVATION');
  if (!Array.isArray(plan?.task_queue) || plan.task_queue.length !== 0)
    errors.push('UNEXPECTED_NONEMPTY_TASK_QUEUE');
  for (const permission of [
    'auto_merge', 'auto_deploy', 'production_access', 'paid_ai_or_external_api',
  ]) {
    if (plan?.execution?.[permission] !== false)
      errors.push('UNSAFE_EXECUTION_POLICY_' + permission.toUpperCase());
  }
  if (plan?.execution?.maximum_parallel_code_agents !== 0)
    errors.push('UNEXPECTED_AGENT_WORKERS');

  for (const [name, body] of [['AGENTS', agents], ['CLAUDE', claude]]) {
    if (!String(body ?? '').includes(ROADMAP_FILE))
      errors.push(name + '_ROADMAP_POINTER_MISSING');
    if (!String(body ?? '').includes(PLAN_FILE))
      errors.push(name + '_PLAN_POINTER_MISSING');
    if (!String(body ?? '').includes('docs/WORK_STATE.md'))
      errors.push(name + '_DOMAIN_GATE_POINTER_MISSING');
  }
  return { ok: errors.length === 0, errors, roadmap_version: '1.0',
    roadmap_sha256: digest(String(roadmap ?? '')) };
}

function safePath(value) {
  if (typeof value !== 'string' || !value || value.includes('\\')
    || value.includes('\0') || value.startsWith('/') || value.startsWith('./')
    || value.endsWith('/') || value.split('/').some(p => p === '.' || p === '..' || p === '')
    || /^[a-zA-Z]:/.test(value)) return false;
  return true;
}
function protectedPath(file) {
  return POLICY_FILES.has(file)
    || file.startsWith('.github/')
    || file.startsWith('supabase/')
    || file.startsWith('docs/portfolio/')
    || file.startsWith('orchestration/')
    || file === '.env' || file.startsWith('.env.')
    || file.startsWith('.git/');
}
function allowedByScope(file, rules) {
  return rules.some(rule => {
    if (typeof rule !== 'string' || !safePath(rule.replace(/\/\*\*$/, '')))
      return false;
    if (rule.endsWith('/**')) {
      const prefix = rule.slice(0, -3);
      return file.startsWith(prefix + '/');
    }
    return rule === file;
  });
}

/** Return a pure decision. Does not execute anything, even for a PASS result. */
export function checkTask({ packet, plan, roadmap, changedFiles = [] }) {
  const errors = [];
  if (plan?.execution?.enabled !== true)
    errors.push('ENFORCER_DISABLED');
  if (packet?.schema !== 'tdr.task-packet.v1')
    errors.push('TASK_SCHEMA_INVALID');
  if (!packet?.task_id || typeof packet.task_id !== 'string')
    errors.push('TASK_ID_MISSING');
  if (packet?.roadmap_version !== '1.0')
    errors.push('TASK_ROADMAP_VERSION_MISMATCH');
  if (!HEX64.test(String(packet?.roadmap_sha256 ?? ''))
      || packet.roadmap_sha256 !== digest(roadmap))
    errors.push('TASK_ROADMAP_HASH_STALE');
  // The packet is stored inside the candidate commit, so it cannot also
  // embed that very commit SHA. Bind the approved BASE here; Stage-1 binds
  // the HEAD to GitHub's immutable event SHA and verified checkout.
  if (!HEX40.test(String(packet?.base_sha ?? '')))
    errors.push('TASK_BASE_SHA_MISSING');
  if (packet?.head_sha !== undefined)
    errors.push('TASK_SELF_REFERENTIAL_HEAD_SHA_FORBIDDEN');
  if (packet?.owner_authorized !== true || !packet.approval_ref)
    errors.push('TASK_OWNER_AUTHORIZATION_MISSING');
  const queueEntry = Array.isArray(plan?.task_queue)
    ? plan.task_queue.find(q => q?.task_id === packet?.task_id) : undefined;
  if (!queueEntry || queueEntry.status !== 'APPROVED'
      || queueEntry.owner_authorized !== true
      || queueEntry.approval_ref !== packet?.approval_ref)
    errors.push('TASK_NOT_APPROVED_IN_CANONICAL_QUEUE');
  if (packet?.execution_mode !== 'OFFLINE')
    errors.push('TASK_MODE_REQUIRES_SEPARATE_POLICY');
  if (!Array.isArray(packet?.required_tests) || !packet.required_tests.length
      || packet.required_tests.some(x => typeof x !== 'string' || !x.trim()))
    errors.push('TASK_REQUIRED_TESTS_MISSING');
  if (!Array.isArray(packet?.allowed_paths) || !packet.allowed_paths.length
      || packet.allowed_paths.some(x => !safePath(String(x).replace(/\/\*\*$/, ''))))
    errors.push('TASK_ALLOWED_PATHS_INVALID');
  if (!Array.isArray(packet?.dependencies))
    errors.push('TASK_DEPENDENCIES_NOT_DECLARED');
  else {
    const done = new Set(plan?.completed_task_ids || []);
    for (const dep of packet.dependencies)
      if (!done.has(dep)) errors.push('TASK_DEPENDENCY_UNSATISFIED:' + dep);
  }
  if (!Array.isArray(changedFiles) || !changedFiles.length)
    errors.push('TASK_CHANGED_FILES_UNAVAILABLE');
  else {
    for (const file of changedFiles) {
      if (!safePath(file)) {
        errors.push('INVALID_CHANGED_PATH');
        continue;
      }
      if (protectedPath(file)) errors.push('PROTECTED_PATH_CHANGE:' + file);
      else if (!allowedByScope(file, Array.isArray(packet?.allowed_paths)
          ? packet.allowed_paths : []))
        errors.push('OUT_OF_SCOPE_CHANGE:' + file);
    }
  }
  const flags = packet?.permissions || {};
  if (flags.production_write || flags.merge || flags.deploy || flags.paid_api
      || flags.network_access || flags.migrations)
    errors.push('TASK_FORBIDDEN_CAPABILITY');
  return { ok: errors.length === 0, errors, task_id: packet?.task_id ?? null };
}

function load(root, rel) {
  const absolute = path.join(root, rel);
  if (!absolute.startsWith(root + path.sep))
    throw new Error('INVALID_ROOT_PATH');
  return fs.readFileSync(absolute, 'utf8');
}

export function main(argv = process.argv.slice(2), root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)), '..')) {
  const plan = JSON.parse(load(root, PLAN_FILE));
  const roadmap = load(root, ROADMAP_FILE);
  const repository = checkRepository({
    plan, roadmap, agents: load(root, REPO_INSTRUCTIONS[0]),
    claude: load(root, REPO_INSTRUCTIONS[1]),
  });
  let result = repository;
  if (argv[0] === '--task-file' && argv[1] && argv[2] === '--changed-files-file'
      && argv[3]) {
    const task = JSON.parse(fs.readFileSync(path.resolve(argv[1]), 'utf8'));
    const files = fs.readFileSync(path.resolve(argv[3]), 'utf8')
      .split(/\r?\n/).filter(Boolean);
    const taskResult = checkTask({ packet: task, plan, roadmap, changedFiles: files });
    result = { ok: repository.ok && taskResult.ok,
      errors: [...repository.errors, ...taskResult.errors],
      task_id: taskResult.task_id };
  } else if (argv.length !== 1 || argv[0] !== '--check-repo') {
    result = { ok: false, errors: ['USAGE: --check-repo OR --task-file <packet.json> --changed-files-file <paths.txt>'] };
  }
  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
  return result.ok ? 0 : 1;
}

if (process.argv[1] && path.resolve(process.argv[1])
    === fileURLToPath(import.meta.url)) {
  try { process.exitCode = main(); }
  catch (err) {
    process.stderr.write(JSON.stringify({ ok: false, errors: ['INPUT_OR_IO_ERROR'],
      detail: String(err?.message || err) }) + '\n');
    process.exitCode = 1;
  }
}
