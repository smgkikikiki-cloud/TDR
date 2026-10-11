#!/usr/bin/env node
/**
 * Stage 1. READ-ONLY pull-request admission inspection.
 * No worker dispatch, no merge, no writes, no credentials, no paid/network AI.
 * The authoritative approval plan/roadmap MUST be read from the PR BASE commit.
 */
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { digest, ROADMAP_FILE, PLAN_FILE } from './preflight.mjs';

const SHA40 = /^[0-9a-f]{40}$/i;
const SHA64 = /^[0-9a-f]{64}$/i;
const MANIFEST = '.tdr/enforcer-task.json';
const ALLOWED_KINDS = new Set(['A', 'M', 'D', 'R', 'C']);
const GUARDED = new Set([
  'AGENTS.md', 'CLAUDE.md', MANIFEST,
  'docs/WORK_STATE.md', 'docs/market-track/ROADMAP.md',
  'docs/vehicle-db/VEHICLE_DB_V3.md',
]);
const ILLEGAL_CAPABILITIES = [
  'production_write', 'merge', 'deploy', 'paid_api', 'network_access',
  'migrations', 'ice_r6', 'ice_r7', 'ice_r8', 'writer',
];

function validPath(p) {
  return typeof p === 'string' && !!p && !p.includes('\\') && !p.includes('\0')
    && !p.startsWith('/') && !/^[A-Za-z]:/.test(p)
    && p.split('/').every(part => !!part && part !== '.' && part !== '..');
}
function reserved(p) {
  return GUARDED.has(p) || p.startsWith('.github/')
    || p.startsWith('docs/portfolio/') || p.startsWith('orchestration/')
    || p.startsWith('supabase/') || p.startsWith('.env')
    || p.startsWith('.git/');
}
function within(file, allowed) {
  return allowed.some(p => typeof p === 'string' && validPath(p.replace(/\/\*\*$/, ''))
    && (p.endsWith('/**') ? file.startsWith(p.slice(0, -3) + '/') : file === p));
}
function sameArray(a, b) {
  return Array.isArray(a) && Array.isArray(b)
    && a.length === b.length && a.every((v, i) => v === b[i]);
}
function falseOrAbsent(x) {
  return x === false || x === undefined;
}

/** git diff --name-status -z [BASE...HEAD] including both sides of renames. */
export function parseDiffNameStatus(bytes) {
  if (!Buffer.isBuffer(bytes)) throw new Error('DIFF_MUST_BE_BUFFER');
  const fields = bytes.toString('utf8').split('\0');
  if (fields.pop() !== '') throw new Error('DIFF_NOT_NUL_TERMINATED');
  const out = [];
  for (let i = 0; i < fields.length;) {
    const status = fields[i++];
    if (!/^[AMDRC][0-9]*$/.test(status)) throw new Error('UNSUPPORTED_DIFF_STATUS:' + status);
    const kind = status[0];
    if (!ALLOWED_KINDS.has(kind)) throw new Error('UNSUPPORTED_DIFF_KIND');
    const paths = (kind === 'R' || kind === 'C') ? [fields[i++], fields[i++]] : [fields[i++]];
    if (paths.some(p => !validPath(p))) throw new Error('INVALID_DIFF_PATH');
    out.push({ kind, paths });
  }
  return out;
}
function normalizedChanges(changes) {
  if (!Array.isArray(changes) || changes.length === 0) throw new Error('NO_DIFF_ENTRIES');
  const all = [];
  for (const change of changes) {
    if (!change || !ALLOWED_KINDS.has(change.kind)
      || !Array.isArray(change.paths)
      || change.paths.length !== ('RC'.includes(change.kind) ? 2 : 1))
      throw new Error('INVALID_DIFF_ENTRY');
    for (const p of change.paths) {
      if (!validPath(p)) throw new Error('INVALID_CHANGED_PATH');
      all.push(p);
    }
  }
  return [...new Set(all)].sort();
}

/**
 * Pure inspection against owner-controlled BASE plan. Outcome is only admission,
 * not proof tests ran / GH branch rules are configured / any human read docs.
 */
export function inspectPr({ event, basePlan, baseRoadmap, baseAgents,
  baseClaude, packet, changes, headFileModes = {}, baseContracts = {},
  candidateHasManifest = false }) {
  const errors = [];
  const warning = [];
  // Validate base-commit roadmap authority independently of the candidate.
  // Do NOT use Stage-0's permanently-disabled checkRepository here: this
  // pure checker needs to test hypothetical future offline authorization in
  // memory without changing the currently disabled repository plan.
  if (basePlan?.schema !== 'tdr.portfolio.approved-roadmap.v1.0'
      || basePlan?.approval?.status !== 'OWNER_APPROVED'
      || basePlan?.approval?.roadmap_version !== '1.0'
      || basePlan?.roadmap_authoritative_file !== ROADMAP_FILE)
    errors.push('TRUSTED_BASE_ROADMAP_POLICY_INVALID');
  if (!String(baseRoadmap ?? '').startsWith('# TDR Master Development Roadmap v1.0'))
    errors.push('TRUSTED_BASE_ROADMAP_CONTENT_INVALID');
  for (const [name, text] of [['AGENTS', baseAgents], ['CLAUDE', baseClaude]]) {
    if (!String(text ?? '').includes(ROADMAP_FILE)
        || !String(text ?? '').includes(PLAN_FILE)
        || !String(text ?? '').includes('docs/WORK_STATE.md'))
      errors.push('TRUSTED_BASE_' + name + '_BOOTSTRAP_MISSING');
  }
  for (const cap of ['auto_merge', 'auto_deploy', 'production_access',
    'paid_ai_or_external_api']) {
    if (basePlan?.execution?.[cap] !== false)
      errors.push('TRUSTED_BASE_UNSAFE_PERMISSION:' + cap);
  }
  const pr = event?.pull_request;
  const baseSha = pr?.base?.sha, headSha = pr?.head?.sha;
  if (!SHA40.test(String(baseSha ?? '')) || !SHA40.test(String(headSha ?? '')))
    errors.push('GITHUB_EVENT_SHA_INVALID');
  if (event?.repository?.full_name !== 'smgkikikiki-cloud/TDR')
    errors.push('UNEXPECTED_REPOSITORY');
  if (pr?.base?.ref !== 'main') errors.push('UNEXPECTED_BASE_BRANCH');
  if (!Number.isInteger(pr?.number) || pr.number < 1)
    errors.push('PR_NUMBER_INVALID');
  let files = [];
  try { files = normalizedChanges(changes); }
  catch (e) { errors.push('DIFF_INVALID:' + e.message); }
  const risks = files.filter(reserved);
  if (risks.length) warning.push('SENSITIVE_FILES_CHANGED:' + risks.join(','));
  const branch = pr?.head?.ref;
  const enforcerBranch = typeof branch === 'string' && branch.startsWith('enforcer/');
  const managed = candidateHasManifest || enforcerBranch;
  if (!managed) {
    // Existing PRs are explicitly NOT silently converted to managed tasks.
    // This is an OBSERVATION result, never a verified Enforcer approval.
    warning.push('UNMANAGED_PR_NOT_TASK_AUTHORIZED');
    return { ok: errors.length === 0, admission: 'UNMANAGED_AUDIT_ONLY',
      enforcerAuthorized: false, errors, warnings: warning, changedFiles: files,
      baseSha, headSha, prNumber: pr?.number ?? null };
  }
  if (!packet || typeof packet !== 'object') {
    errors.push('MANAGED_TASK_PACKET_MISSING');
    packet = {};
  }
  if (basePlan?.execution?.enabled !== true)
    errors.push('ENFORCER_DISABLED_IN_TRUSTED_BASE');
  if (packet.schema !== 'tdr.task-packet.v1') errors.push('PACKET_SCHEMA_UNRECOGNIZED');
  if (packet.roadmap_version !== '1.0'
    || packet.roadmap_sha256 !== digest(baseRoadmap)
    || !SHA64.test(String(packet.roadmap_sha256 ?? '')))
    errors.push('PINNED_ROADMAP_MISMATCH');
  // A manifest committed inside HEAD cannot embed its own HEAD SHA:
  // that would be a cryptographic self-reference. Bind the BASE SHA in
  // the manifest, and get the immutable HEAD SHA from GitHub's event +
  // independently checked git checkout at CI runtime instead.
  if (packet.base_sha !== baseSha || !SHA40.test(String(packet.base_sha ?? '')))
    errors.push('PACKET_BASE_SHA_STALE');
  if (packet.head_sha !== undefined)
    errors.push('SELF_REFERENTIAL_HEAD_SHA_FORBIDDEN');
  if (packet.owner_authorized !== true || typeof packet.approval_ref !== 'string'
    || !packet.approval_ref.trim()) errors.push('PACKET_OWNER_APPROVAL_MISSING');
  if (typeof packet.task_id !== 'string' || !/^[A-Z0-9][A-Z0-9_.-]{1,79}$/.test(packet.task_id))
    errors.push('PACKET_ID_INVALID');
  if (packet.execution_mode !== 'OFFLINE')
    errors.push('NONOFFLINE_TASK_NOT_SUPPORTED');
  if (!Array.isArray(packet.dependencies)
    || packet.dependencies.some(d => typeof d !== 'string' || !d))
    errors.push('PACKET_DEPENDENCIES_INVALID');
  if (!Array.isArray(packet.allowed_paths) || !packet.allowed_paths.length)
    errors.push('PACKET_SCOPE_MISSING');
  if (!Array.isArray(packet.required_tests) || !packet.required_tests.length)
    errors.push('PACKET_TESTS_MISSING');

  const authorized = Array.isArray(basePlan?.task_queue) ?
    basePlan.task_queue.find(t => t?.task_id === packet.task_id) : null;
  if (!authorized || authorized.status !== 'APPROVED'
    || authorized.owner_authorized !== true
    || authorized.approval_ref !== packet.approval_ref
    || authorized.roadmap_version !== packet.roadmap_version
    || authorized.roadmap_sha256 !== packet.roadmap_sha256
    || authorized.base_sha !== baseSha
    || !sameArray(authorized.allowed_paths, packet.allowed_paths)
    || !sameArray(authorized.required_tests, packet.required_tests)
    || !sameArray(authorized.dependencies, packet.dependencies)
    || authorized.execution_mode !== 'OFFLINE')
    errors.push('TRUSTED_BASE_TASK_APPROVAL_MISSING_OR_CHANGED');

  const done = new Set(basePlan?.completed_task_ids || []);
  for (const dep of Array.isArray(packet.dependencies) ? packet.dependencies : [])
    if (!done.has(dep)) errors.push('DEPENDENCY_NOT_ACCEPTED:' + dep);

  for (const cap of ILLEGAL_CAPABILITIES)
    if (!falseOrAbsent(packet?.permissions?.[cap])
      || !falseOrAbsent(authorized?.permissions?.[cap]))
      errors.push('FORBIDDEN_CAPABILITY:' + cap);

  // A domain gate is an independent, versioned BASE-file authorization.
  // Checking only status or "v1" would permit substituting another domain.
  const gate = packet?.domain_gate, trustedGate = authorized?.domain_gate;
  if (gate?.status !== 'CLEARED' || trustedGate?.status !== 'CLEARED'
    || typeof gate?.domain !== 'string' || !gate.domain
    || gate.domain !== trustedGate.domain
    || typeof gate?.contract_path !== 'string'
    || gate.contract_path !== trustedGate.contract_path
    || !validPath(gate.contract_path) || !gate.contract_path.startsWith('docs/')
    || gate.contract_version !== trustedGate.contract_version
    || !gate.contract_version
    || !SHA64.test(String(gate.contract_sha256 ?? ''))
    || gate.contract_sha256 !== trustedGate.contract_sha256
    || typeof baseContracts[gate.contract_path] !== 'string'
    || digest(baseContracts[gate.contract_path]) !== gate.contract_sha256)
    errors.push('DOMAIN_GATE_NOT_INDEPENDENTLY_CLEARED');

  for (const p of files) {
    if (p === MANIFEST) continue; // manifest itself may change, but never authoritative
    if (reserved(p)) errors.push('MANAGED_TASK_PROTECTED_FILE:' + p);
    else if (!within(p, Array.isArray(authorized?.allowed_paths) ? authorized.allowed_paths : []))
      errors.push('OUT_OF_SCOPE_FILE:' + p);
  }
  // All HEAD-present changed paths must have a Git tree mode observed by
  // the independent checker. Deleted files and pre-rename paths have no
  // required HEAD entry, but *both* paths were already scope-checked above.
  for (const entry of Array.isArray(changes) ? changes : []) {
    const currentPaths = entry.kind === 'D' ? []
      : ('RC'.includes(entry.kind) ? [entry.paths[1]] : entry.paths);
    for (const p of currentPaths) {
      if (!Object.hasOwn(headFileModes, p))
        errors.push('HEAD_FILE_MODE_MISSING:' + p);
      else if (!['100644', '100755'].includes(headFileModes[p]))
        errors.push('UNSAFE_GIT_FILE_MODE:' + p + ':' + headFileModes[p]);
    }
  }
  // No deployed CI/test attestation or side effect follows a passing result.
  return { ok: errors.length === 0, admission: errors.length ? 'DENIED' : 'CHECKS_PASS_ONLY',
    enforcerAuthorized: false, errors, warnings: warning, changedFiles: files,
    baseSha, headSha, prNumber: pr?.number ?? null };
}
function git(repo, args, encoding = 'utf8') {
  return execFileSync('git', args, { cwd: repo, encoding, timeout: 15000,
    stdio: ['ignore', 'pipe', 'pipe'], maxBuffer: 16 * 1024 * 1024 });
}
function readPolicy(root, rel) {
  if (!validPath(rel)) throw new Error('INVALID_POLICY_FILE_PATH');
  const full = path.join(root, rel);
  if (!fs.lstatSync(full).isFile()) throw new Error('POLICY_FILE_NOT_REGULAR:' + rel);
  return fs.readFileSync(full, 'utf8');
}
function findManifest(root) {
  const loc = path.join(root, MANIFEST);
  if (!fs.existsSync(loc)) return null;
  if (!fs.lstatSync(loc).isFile()) throw new Error('MANIFEST_NOT_REGULAR_FILE');
  return JSON.parse(fs.readFileSync(loc, 'utf8'));
}
function modeMap(repo, entries) {
  const m = {};
  for (const e of entries) for (const p of e.paths) {
    if (e.kind === 'D' || (('RC'.includes(e.kind)) && p === e.paths[0]))
      continue;
    const result = git(repo, ['ls-tree', 'HEAD', '--', p]);
    const match = /^([0-7]{6}) [a-z]+ [0-9a-f]{40}\t/.exec(result);
    if (!match) throw new Error('GIT_FILE_MODE_NOT_FOUND:' + p);
    m[p] = match[1];
  }
  return m;
}
export function cli(argv) {
  if (argv.length !== 6 || argv[0] !== '--event'
    || argv[2] !== '--policy-root' || argv[4] !== '--candidate-root')
    throw new Error('USAGE: --event <github_event.json> --policy-root <trusted-base-checkout> --candidate-root <head-checkout>');
  const event = JSON.parse(fs.readFileSync(path.resolve(argv[1]), 'utf8'));
  const policyRoot = path.resolve(argv[3]), repo = path.resolve(argv[5]);
  const expectedBase = event?.pull_request?.base?.sha;
  const expectedHead = event?.pull_request?.head?.sha;
  if (git(policyRoot, ['rev-parse', 'HEAD']).trim() !== expectedBase)
    throw new Error('TRUSTED_POLICY_CHECKOUT_IS_NOT_PR_BASE_SHA');
  if (git(repo, ['rev-parse', 'HEAD']).trim() !== expectedHead)
    throw new Error('CANDIDATE_CHECKOUT_IS_NOT_PR_HEAD_SHA');
  // Make sure the candidate git graph contains both commits. Never silently
  // fall back to a single-dot diff or an incomplete changed-file list.
  const raw = git(repo, ['diff', '--name-status', '-z', '--find-renames',
    expectedBase + '...' + expectedHead], 'buffer');
  const changes = parseDiffNameStatus(raw);
  const packet = findManifest(repo);
  const basePlan = JSON.parse(readPolicy(policyRoot, PLAN_FILE));
  const entry = Array.isArray(basePlan.task_queue)
    ? basePlan.task_queue.find(t => t?.task_id === packet?.task_id) : null;
  const contractPath = entry?.domain_gate?.contract_path;
  const baseContracts = {};
  if (typeof contractPath === 'string') {
    // Fail closed rather than trusting packet paths or attempting to read
    // outside the base checkout; only a known approved queue path is read.
    if (!validPath(contractPath) || !contractPath.startsWith('docs/'))
      throw new Error('TRUSTED_QUEUE_CONTRACT_PATH_UNSAFE');
    baseContracts[contractPath] = readPolicy(policyRoot, contractPath);
  }
  return inspectPr({
    event, changes, packet, candidateHasManifest: packet !== null,
    basePlan, baseContracts,
    baseRoadmap: readPolicy(policyRoot, ROADMAP_FILE),
    baseAgents: readPolicy(policyRoot, 'AGENTS.md'),
    baseClaude: readPolicy(policyRoot, 'CLAUDE.md'),
    headFileModes: modeMap(repo, changes),
  });
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const r = cli(process.argv.slice(2));
    process.stdout.write(JSON.stringify(r, null, 2) + '\n');
    process.exitCode = r.ok ? 0 : 1;
  } catch (err) {
    process.stderr.write(JSON.stringify({ ok: false, admission: 'DENIED',
      errors: ['ADMISSION_INPUT_ERROR', String(err?.message || err)] }) + '\n');
    process.exitCode = 1;
  }
}
