import test from 'node:test';
import assert from 'node:assert/strict';
import { checkRepository, checkTask, digest, ROADMAP_FILE, PLAN_FILE } from './preflight.mjs';

const SHA = 'a'.repeat(40);
const roadmap = '# TDR Master Development Roadmap v1.0\nApproved contents for a synthetic test.\n';
function plan() {
  return {
    schema: 'tdr.portfolio.approved-roadmap.v1.0',
    approval: { status: 'OWNER_APPROVED', roadmap_version: '1.0' },
    roadmap_authoritative_file: ROADMAP_FILE,
    execution: { enabled: false, auto_merge: false, auto_deploy: false,
      production_access: false, paid_ai_or_external_api: false,
      maximum_parallel_code_agents: 0 },
    task_queue: [],
  };
}
const pointers = ROADMAP_FILE + '\n' + PLAN_FILE + '\n' + 'docs/WORK_STATE.md';
function packet() {
  return {
    schema: 'tdr.task-packet.v1', task_id: 'SYN-001',
    roadmap_version: '1.0', roadmap_sha256: digest(roadmap),
    base_sha: SHA,
    owner_authorized: true, approval_ref: 'synthetic-owner-go',
    execution_mode: 'OFFLINE',
    allowed_paths: ['lib/analysis/**', 'scripts/check-analysis.mjs'],
    required_tests: ['node --test orchestration/preflight.test.mjs'],
    dependencies: [],
    permissions: { production_write: false, merge: false, deploy: false,
      paid_api: false, network_access: false, migrations: false },
  };
}
function simulatedApprovedPlan() {
  const p = plan();
  p.execution.enabled = true; // in-memory fixture ONLY: never written to repository.
  p.task_queue = [{ task_id: 'SYN-001', status: 'APPROVED',
    owner_authorized: true, approval_ref: 'synthetic-owner-go' }];
  return p;
}
const args = () => ({
  packet: packet(), plan: simulatedApprovedPlan(), roadmap,
  changedFiles: ['lib/analysis/pressure.ts'],
});

test('repository is valid only with owner-approved v1 plan and instruction pointers', () => {
  const valid = checkRepository({ plan: plan(), roadmap, agents: pointers, claude: pointers });
  assert.equal(valid.ok, true, valid.errors.join(','));
  assert.equal(valid.roadmap_sha256, digest(roadmap));
});
test('repository fails closed if agent instruction omits roadmap', () => {
  const res = checkRepository({ plan: plan(), roadmap, agents: pointers, claude: PLAN_FILE + ' docs/WORK_STATE.md' });
  assert.equal(res.ok, false);
  assert.ok(res.errors.includes('CLAUDE_ROADMAP_POINTER_MISSING'));
});
test('repository rejects unapproved autonomous activation or newly queued tasks', () => {
  const p = plan(); p.execution.enabled = true;
  p.task_queue = [{ task_id: 'UNEXPECTED' }];
  const res = checkRepository({ plan: p, roadmap, agents: pointers, claude: pointers });
  assert.ok(res.errors.includes('UNEXPECTED_ENFORCER_ACTIVATION'));
  assert.ok(res.errors.includes('UNEXPECTED_NONEMPTY_TASK_QUEUE'));
});
test('real disabled plan refuses to dispatch regardless of a claimed task approval', () => {
  const x = args(); x.plan = plan();
  assert.equal(checkTask(x).ok, false);
  assert.ok(checkTask(x).errors.includes('ENFORCER_DISABLED'));
});
test('synthetic in-memory approved packet passes only pure admission checks', () => {
  const x = checkTask(args());
  assert.equal(x.ok, true, x.errors.join(','));
});
test('task with fabricated owner claim but no canonical queue entry fails', () => {
  const x = args(); x.plan.task_queue = [];
  assert.ok(checkTask(x).errors.includes('TASK_NOT_APPROVED_IN_CANONICAL_QUEUE'));
});
test('task without explicit owner authorization fails', () => {
  const x = args(); x.packet.owner_authorized = false;
  assert.ok(checkTask(x).errors.includes('TASK_OWNER_AUTHORIZATION_MISSING'));
});
test('stale or wrong roadmap hash fails', () => {
  const x = args(); x.packet.roadmap_sha256 = 'f'.repeat(64);
  assert.ok(checkTask(x).errors.includes('TASK_ROADMAP_HASH_STALE'));
});
test('invalid base SHA cannot pass', () => {
  const x = args(); x.packet.base_sha = 'HEAD';
  assert.ok(checkTask(x).errors.includes('TASK_BASE_SHA_MISSING'));
});
test('packet cannot self-reference its own commit HEAD SHA', () => {
  const x = args(); x.packet.head_sha = SHA;
  assert.ok(checkTask(x).errors.includes('TASK_SELF_REFERENTIAL_HEAD_SHA_FORBIDDEN'));
});
test('out-of-scope file change fails', () => {
  const x = args(); x.changedFiles = ['app/page.tsx'];
  assert.ok(checkTask(x).errors.includes('OUT_OF_SCOPE_CHANGE:app/page.tsx'));
});
test('protected governance and DB changes fail even if task scope includes them', () => {
  for (const file of ['AGENTS.md', 'docs/WORK_STATE.md',
      '.github/workflows/untrusted.yml', 'supabase/migrations/v99.sql',
      'docs/portfolio/portfolio.plan.json', 'orchestration/preflight.mjs', '.env.local']) {
    const x = args(); x.packet.allowed_paths = [file]; x.changedFiles = [file];
    assert.ok(checkTask(x).errors.includes('PROTECTED_PATH_CHANGE:' + file), file);
  }
});
test('malformed or traversing path fails', () => {
  const x = args(); x.changedFiles = ['../secrets.txt'];
  assert.ok(checkTask(x).errors.includes('INVALID_CHANGED_PATH'));
});
test('deferred dependencies fail closed', () => {
  const x = args(); x.packet.dependencies = ['PR200-R6'];
  assert.ok(checkTask(x).errors.includes('TASK_DEPENDENCY_UNSATISFIED:PR200-R6'));
});
test('empty test list fails closed', () => {
  const x = args(); x.packet.required_tests = [];
  assert.ok(checkTask(x).errors.includes('TASK_REQUIRED_TESTS_MISSING'));
});
test('any request for live resources fails on Stage-0 policy', () => {
  const x = args(); x.packet.permissions.network_access = true;
  assert.ok(checkTask(x).errors.includes('TASK_FORBIDDEN_CAPABILITY'));
});
test('task without file diff cannot pass', () => {
  const x = args(); x.changedFiles = [];
  assert.ok(checkTask(x).errors.includes('TASK_CHANGED_FILES_UNAVAILABLE'));
});
test('non-offline packet cannot pass Stage-0 admission', () => {
  const x = args(); x.packet.execution_mode = 'PRODUCTION';
  assert.ok(checkTask(x).errors.includes('TASK_MODE_REQUIRES_SEPARATE_POLICY'));
});
