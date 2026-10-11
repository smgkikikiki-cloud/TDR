import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { classifyHistoricalPr, cli } from './historical-pr-audit.mjs';

const SHA1 = 'a'.repeat(40);
const SHA2 = 'b'.repeat(40);
function event(headRef = 'codex/legacy-no-enforcer', base = SHA1, head = SHA2) {
  return {
    repository: { full_name: 'smgkikikiki-cloud/TDR' },
    pull_request: { number: 203, base: { ref: 'main', sha: base },
      head: { ref: headRef, sha: head } },
  };
}
const add = file => ({ kind: 'A', paths: [file] });

test('old #201-style domain-state change remains explicitly audit-only', () => {
  const x = classifyHistoricalPr({ event: event('claude/identity-bootstrap'),
    changes: [add('automotive/vehicle_master/identity_bootstrap/engine/plan.py'),
      { kind: 'M', paths: ['docs/WORK_STATE.md'] }] });
  assert.equal(x.ok, true);
  assert.equal(x.admission, 'UNMANAGED_AUDIT_ONLY');
  assert.equal(x.enforcerAuthorized, false);
  assert.ok(x.warnings.some(s => s.startsWith('DOMAIN_STATE_OR_SCHEMA_CHANGED_NOT_ENFORCER_APPROVED')));
});
test('old #203-style normal PR is audit-only, never task admitted', () => {
  const x = classifyHistoricalPr({ event: event(),
    changes: [add('automotive/vehicle_master/catalog_maintainer/simulator.py')] });
  assert.equal(x.ok, true);
  assert.equal(x.enforcerAuthorized, false);
  assert.equal(x.admission, 'UNMANAGED_AUDIT_ONLY');
});
test('historical managed branch is DENIED, not bootstrap accepted', () => {
  const x = classifyHistoricalPr({ event: event('enforcer/unauthorized'),
    changes: [add('automotive/test.py')] });
  assert.equal(x.ok, false);
  assert.equal(x.admission, 'DENIED');
  assert.ok(x.errors.includes('HISTORICAL_MANAGED_TASK_DENIED'));
});
test('historical task packet is DENIED even without an enforcer/ branch', () => {
  const x = classifyHistoricalPr({ event: event('feat/legacy'),
    changes: [add('data/ok.csv')], candidateHasManifest: true });
  assert.ok(x.errors.includes('HISTORICAL_MANAGED_TASK_DENIED'));
});
test('candidate governance tampering is rejected and never executed', () => {
  for (const file of [
    'AGENTS.md', 'CLAUDE.md',
    'orchestration/preflight.test.mjs',
    'orchestration/historical-pr-audit.mjs',
    '.github/workflows/enforcer-pr-admission.yml',
    'docs/portfolio/portfolio.plan.json',
    '.tdr/attempt.json',
  ]) {
    const x = classifyHistoricalPr({ event: event(), changes: [add(file)] });
    assert.ok(x.errors.includes('HISTORICAL_GOVERNANCE_CHANGE_REQUIRES_MODERN_REVIEW'), file);
    assert.equal(x.enforcerAuthorized, false);
  }
});
test('governance-path rename checks BOTH old and new', () => {
  const x = classifyHistoricalPr({ event: event(),
    changes: [{ kind: 'R', paths: ['src/not-a-governance-file.py',
      'orchestration/preflight.test.mjs'] }] });
  assert.equal(x.admission, 'DENIED');
  assert.ok(x.changedFiles.includes('src/not-a-governance-file.py'));
  assert.ok(x.changedFiles.includes('orchestration/preflight.test.mjs'));
});
test('empty legacy PR diff fails closed instead of claiming audited', () => {
  const x = classifyHistoricalPr({ event: event(), changes: [] });
  assert.equal(x.ok, false);
  assert.equal(x.admission, 'DENIED');
  assert.ok(x.errors.includes('DIFF_NOT_AVAILABLE_OR_EMPTY'));
});
test('non-governance source file rename stays audit-only', () => {
  const x = classifyHistoricalPr({ event: event(),
    changes: [{ kind: 'R', paths: ['src/old.py', 'src/new.py'] }] });
  assert.equal(x.admission, 'UNMANAGED_AUDIT_ONLY');
  assert.deepEqual(x.changedFiles, ['src/new.py','src/old.py']);
});

test('invalid event repository, SHA and diff fail closed', () => {
  const e = event(); e.repository.full_name = 'attacker/TDR'; e.pull_request.head.sha = 'fake';
  const x = classifyHistoricalPr({ event: e, changes: null });
  assert.ok(x.errors.includes('REPOSITORY_MISMATCH'));
  assert.ok(x.errors.includes('EVENT_SHA_INVALID'));
  assert.ok(x.errors.includes('DIFF_NOT_AVAILABLE_OR_EMPTY'));
  assert.equal(x.admission, 'DENIED');
});

function git(cwd, ...args) {
  return execFileSync('git', args, {
    cwd, encoding: 'utf8', timeout: 15000,
    env: { ...process.env, GIT_CONFIG_NOSYSTEM: '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
  }).trim();
}
function write(root, file, body) {
  const destination = path.join(root, file);
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(destination, body);
}
function commit(root, text) {
  git(root, 'add', '-A');
  git(root, 'commit', '-q', '-m', text);
  return git(root, 'rev-parse', 'HEAD');
}
function fixture(mutate, { protectedBase = false } = {}) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'tdr-historical-ci-'));
  try {
    const source = path.join(tmp, 'source');
    fs.mkdirSync(source);
    git(source, 'init', '-q', '-b', 'main');
    git(source, 'config', 'user.name', 'TDR CI regression');
    git(source, 'config', 'user.email', 'ci@example.invalid');
    write(source, 'src/existing.py', 'before\n');
    if (protectedBase)
      write(source, 'orchestration/pr-admission.mjs', '// modern trusted BASE\n');
    const base = commit(source, 'pre-enforcer PR base');
    mutate(source);
    const head = commit(source, 'legacy PR candidate');
    const policy = path.join(tmp, 'policy');
    const candidate = path.join(tmp, 'candidate');
    git(tmp, 'clone', '-q', source, policy);
    git(tmp, 'clone', '-q', source, candidate);
    git(policy, 'checkout', '--detach', '-q', base);
    git(candidate, 'checkout', '--detach', '-q', head);
    const payload = path.join(tmp, 'event.json');
    fs.writeFileSync(payload, JSON.stringify(event('codex/legacy', base, head)));
    const call = () => cli(['--event', payload,
      '--policy-root', policy, '--candidate-root', candidate]);
    return { tmp, source, base, head, policy, candidate, payload, call };
  } catch (err) {
    fs.rmSync(tmp, { recursive: true, force: true });
    throw err;
  }
}
function withFixture(mutate, callback, options = {}) {
  const x = fixture(mutate, options);
  try { callback(x); }
  finally { fs.rmSync(x.tmp, { recursive: true, force: true }); }
}
test('isolated real Git history: legacy PR without scripts passes audit-only', () => {
  withFixture(dir => write(dir, 'src/new.py', 'candidate\n'), x => {
    const r = x.call();
    assert.equal(r.ok, true);
    assert.equal(r.admission, 'UNMANAGED_AUDIT_ONLY');
    assert.equal(r.enforcerAuthorized, false);
    assert.equal(r.headSha, x.head);
    assert.equal(r.baseSha, x.base);
  });
});
test('isolated real Git: legacy PR with WORK_STATE.md remains audit-only with warning', () => {
  withFixture(dir => write(dir, 'docs/WORK_STATE.md', 'domain note\n'), x => {
    const r = x.call();
    assert.equal(r.ok, true);
    assert.equal(r.admission, 'UNMANAGED_AUDIT_ONLY');
    assert.ok(r.warnings.some(s => s.startsWith('DOMAIN_STATE_OR_SCHEMA_CHANGED_NOT_ENFORCER_APPROVED')));
  });
});
test('isolated real Git: task packet denied with no owner authorization', () => {
  withFixture(dir => write(dir, '.tdr/enforcer-task.json',
    JSON.stringify({ owner_authorized: false })), x => {
    const r = x.call();
    assert.equal(r.ok, false);
    assert.equal(r.admission, 'DENIED');
    assert.ok(r.errors.includes('HISTORICAL_MANAGED_TASK_DENIED'));
  });
});
test('isolated real Git: candidate tampers with Enforcer file -> DENIED', () => {
  withFixture(dir => write(dir, 'orchestration/preflight.test.mjs',
    "process.stdout.write('fake-green');\n"), x => {
    const r = x.call();
    assert.equal(r.ok, false);
    assert.ok(r.errors.includes('HISTORICAL_GOVERNANCE_CHANGE_REQUIRES_MODERN_REVIEW'));
  });
});
test('isolated real Git: rename into governance path -> DENIED', () => {
  withFixture(dir => {
    fs.mkdirSync(path.join(dir, 'orchestration'), { recursive: true });
    git(dir, 'mv', 'src/existing.py', 'orchestration/preflight.test.mjs');
  }, x => {
    const r = x.call();
    assert.equal(r.admission, 'DENIED');
    assert.ok(r.changedFiles.includes('src/existing.py'));
    assert.ok(r.changedFiles.includes('orchestration/preflight.test.mjs'));
  });
});
test('isolated real Git: wrong event HEAD SHA rejected BEFORE classifying', () => {
  withFixture(dir => write(dir, 'src/new.py', 'new\n'), x => {
    const e = JSON.parse(fs.readFileSync(x.payload, 'utf8'));
    e.pull_request.head.sha = 'f'.repeat(40);
    fs.writeFileSync(x.payload, JSON.stringify(e));
    assert.throws(x.call, /CANDIDATE_HEAD_CHECKOUT_MISMATCH/);
  });
});
test('isolated real Git: modern base checker must be used, not historical fallback', () => {
  withFixture(dir => write(dir, 'src/new.py', 'new\n'), x => {
    assert.throws(x.call, /NOT_HISTORICAL_BASE_USE_BASE_POLICY/);
  }, { protectedBase: true });
});
