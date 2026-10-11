import test from 'node:test';
import assert from 'node:assert/strict';
import { inspectPr, parseDiffNameStatus } from './pr-admission.mjs';
import { digest, ROADMAP_FILE, PLAN_FILE } from './preflight.mjs';

const BASE = 'a'.repeat(40), HEAD = 'b'.repeat(40);
const roadmap = '# TDR Master Development Roadmap v1.0\nSynthetic reviewed contract\n';
const refs = ROADMAP_FILE + '\n' + PLAN_FILE + '\ndocs/WORK_STATE.md';
function event() {
  return { repository: { full_name: 'smgkikikiki-cloud/TDR' },
    pull_request: { number: 206, base: { ref: 'main', sha: BASE },
      head: { ref: 'enforcer/SYN-001', sha: HEAD } } };
}
function packet() {
  return {
    schema: 'tdr.task-packet.v1', task_id: 'SYN-001',
    roadmap_version: '1.0', roadmap_sha256: digest(roadmap),
    base_sha: BASE, owner_authorized: true,
    approval_ref: 'OWNER-REF-1', execution_mode: 'OFFLINE',
    allowed_paths: ['lib/analysis/**'],
    required_tests: ['node --test tests/pressure.test.mjs'],
    dependencies: [],
    domain_gate: { status: 'CLEARED', contract_version: 'v1' },
    permissions: { production_write: false, merge: false, deploy: false,
      paid_api: false, network_access: false, migrations: false },
  };
}
function plan(enabled = false) {
  const p = {
    schema: 'tdr.portfolio.approved-roadmap.v1.0',
    approval: { status: 'OWNER_APPROVED', roadmap_version: '1.0' },
    roadmap_authoritative_file: ROADMAP_FILE,
    execution: { enabled, auto_merge: false, auto_deploy: false,
      production_access: false, paid_ai_or_external_api: false,
      maximum_parallel_code_agents: 0 },
    completed_task_ids: [],
    task_queue: [],
  };
  if (enabled) {
    const q = packet();
    p.task_queue = [{ task_id: q.task_id, status: 'APPROVED',
      owner_authorized: true, approval_ref: q.approval_ref,
      roadmap_version: q.roadmap_version, roadmap_sha256: q.roadmap_sha256,
      base_sha: q.base_sha, allowed_paths: q.allowed_paths,
      required_tests: q.required_tests, dependencies: q.dependencies,
      execution_mode: 'OFFLINE', domain_gate: q.domain_gate, permissions: q.permissions }];
  }
  return p;
}
function inputs(enabled = false) {
  return {
    event: event(), basePlan: plan(enabled), baseRoadmap: roadmap,
    baseAgents: refs, baseClaude: refs, packet: packet(),
    changes: [{ kind: 'A', paths: ['.tdr/enforcer-task.json'] },
      { kind: 'M', paths: ['lib/analysis/pressure.ts'] }],
    headFileModes: {
      '.tdr/enforcer-task.json': '100644',
      'lib/analysis/pressure.ts': '100644',
    },
    candidateHasManifest: true,
  };
}
function run(change) {
  const x = inputs(true); change(x);
  return inspectPr(x);
}

test('parses NUL diff, including both rename sides, not only destination', () => {
  const raw = Buffer.from('R100\0lib/analysis/original.ts\0lib/analysis/renamed.ts\0M\0lib/analysis/new.ts\0');
  assert.deepEqual(parseDiffNameStatus(raw), [
    { kind: 'R', paths: ['lib/analysis/original.ts', 'lib/analysis/renamed.ts'] },
    { kind: 'M', paths: ['lib/analysis/new.ts'] },
  ]);
});
test('reject malformed diff and unrecognized statuses', () => {
  assert.throws(() => parseDiffNameStatus(Buffer.from('R100\0a.ts\0')));
  assert.throws(() => parseDiffNameStatus(Buffer.from('T\0a.ts\0')));
});
test('rejects path traversal and absolute path in binary diff', () => {
  assert.throws(() => parseDiffNameStatus(Buffer.from('A\0../secrets\0')));
  assert.throws(() => parseDiffNameStatus(Buffer.from('A\0/etc/passwd\0')));
});
test('unmanaged legacy PR is audit-only, explicitly never enforcer-approved', () => {
  const x = inputs(); x.event.pull_request.head.ref = 'feat/legacy';
  x.candidateHasManifest = false; x.packet = null;
  x.changes = [{ kind: 'M', paths: ['app/page.tsx'] }];
  const res = inspectPr(x);
  assert.equal(res.ok, true);
  assert.equal(res.admission, 'UNMANAGED_AUDIT_ONLY');
  assert.equal(res.enforcerAuthorized, false);
  assert.ok(res.warnings.includes('UNMANAGED_PR_NOT_TASK_AUTHORIZED'));
});
test('live plan disabled prevents a managed packet even when it asserts approval', () => {
  const res = inspectPr(inputs());
  assert.equal(res.ok, false);
  assert.ok(res.errors.includes('ENFORCER_DISABLED_IN_TRUSTED_BASE'));
  assert.equal(res.enforcerAuthorized, false);
});
test('fully synthetic in-memory trusted base + offline packet can pass pure checks only', () => {
  const res = inspectPr(inputs(true));
  assert.equal(res.ok, true, res.errors.join(','));
  assert.equal(res.admission, 'CHECKS_PASS_ONLY');
  assert.equal(res.enforcerAuthorized, false); // no dispatch implementation.
});
test('fake packet authorization is not accepted without canonical base queue match', () => {
  const res = run(x => { x.basePlan.task_queue = []; });
  assert.ok(res.errors.includes('TRUSTED_BASE_TASK_APPROVAL_MISSING_OR_CHANGED'));
});
test('packet cannot expand path scope beyond canonical approved queue', () => {
  const res = run(x => { x.packet.allowed_paths = ['lib/analysis/**', 'app/**']; });
  assert.ok(res.errors.includes('TRUSTED_BASE_TASK_APPROVAL_MISSING_OR_CHANGED'));
});
test('changed file outside canonical allowlist rejected', () => {
  const res = run(x => { x.changes.push({ kind: 'M', paths: ['app/page.tsx'] }); });
  assert.ok(res.errors.includes('OUT_OF_SCOPE_FILE:app/page.tsx'));
});
test('rename out of allowlist checks both source and destination paths', () => {
  const res = run(x => { x.changes.push({ kind: 'R', paths: ['app/secret.ts', 'lib/analysis/secret.ts'] }); });
  assert.ok(res.errors.includes('OUT_OF_SCOPE_FILE:app/secret.ts'));
});
test('protected roadmap / workflow / database files cannot be changed by managed task', () => {
  for (const p of ['AGENTS.md', '.github/workflows/ci.yml', 'supabase/migrations/0001.sql',
    'docs/WORK_STATE.md', 'docs/portfolio/portfolio.plan.json',
    'orchestration/preflight.mjs', '.env.local']) {
    const res = run(x => { x.changes.push({ kind: 'M', paths: [p] }); });
    assert.ok(res.errors.includes('MANAGED_TASK_PROTECTED_FILE:' + p), p);
  }
});
test('unsafe git mode such as symlink or submodule is rejected', () => {
  const res = run(x => { x.headFileModes['lib/analysis/pressure.ts'] = '120000'; });
  assert.ok(res.errors.some(e => e.startsWith('UNSAFE_GIT_FILE_MODE')));
});
test('not yet accepted dependency blocks task', () => {
  const res = run(x => {
    x.packet.dependencies = ['PR200-R7'];
    x.basePlan.task_queue[0].dependencies = ['PR200-R7'];
  });
  assert.ok(res.errors.includes('DEPENDENCY_NOT_ACCEPTED:PR200-R7'));
});
test('missing independent domain gate blocks task', () => {
  const res = run(x => { x.packet.domain_gate.status = 'REVIEW_REQUIRED'; });
  assert.ok(res.errors.includes('DOMAIN_GATE_NOT_INDEPENDENTLY_CLEARED'));
});
test('task cannot self-authorize live HTTP/paid/Production/merge capability', () => {
  for (const p of ['network_access', 'paid_api', 'production_write', 'merge']) {
    const res = run(x => { x.packet.permissions[p] = true; });
    assert.ok(res.errors.includes('FORBIDDEN_CAPABILITY:' + p));
  }
});
test('stale roadmap hash and base SHA are refused', () => {
  const a = run(x => { x.packet.roadmap_sha256 = 'f'.repeat(64); });
  assert.ok(a.errors.includes('PINNED_ROADMAP_MISMATCH'));
  const b = run(x => { x.packet.base_sha = 'c'.repeat(40); });
  assert.ok(b.errors.includes('PACKET_BASE_SHA_STALE'));
});
test('packet cannot contain its own HEAD SHA (self-reference)', () => {
  const res = run(x => { x.packet.head_sha = HEAD; });
  assert.ok(res.errors.includes('SELF_REFERENTIAL_HEAD_SHA_FORBIDDEN'));
});
test('incorrect GitHub repo and branch blocked even for legacy audit', () => {
  const x = inputs(); x.event.repository.full_name = 'attacker/repo';
  x.event.pull_request.base.ref = 'attacker';
  const res = inspectPr(x);
  assert.ok(res.errors.includes('UNEXPECTED_REPOSITORY'));
  assert.ok(res.errors.includes('UNEXPECTED_BASE_BRANCH'));
});
test('changed plan on PR head cannot authorize task if base plan is disabled', () => {
  const res = inspectPr(inputs(false));
  assert.equal(res.ok, false);
  assert.ok(res.errors.includes('ENFORCER_DISABLED_IN_TRUSTED_BASE'));
});
test('missing managed manifest on enforcer branch fails closed', () => {
  const x = inputs(true); x.candidateHasManifest = false; x.packet = null;
  const res = inspectPr(x);
  assert.ok(res.errors.includes('MANAGED_TASK_PACKET_MISSING'));
});
test('source points to trusted roadmap, NOT feature branch', () => {
  const res = run(x => { x.baseAgents = 'docs/WORK_STATE.md'; });
  assert.ok(res.errors.includes('TRUSTED_BASE_AGENTS_BOOTSTRAP_MISSING'));
});
