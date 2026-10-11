import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(moduleDir, '..');
const cli = path.join(moduleDir, 'pr-admission.mjs');

function command(cwd, ...args) {
  return execFileSync('git', args, { cwd, encoding: 'utf8',
    env: { ...process.env, GIT_CONFIG_NOSYSTEM: '1' },
    timeout: 15000, stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}
function commit(repo, message) {
  command(repo, 'add', '-A');
  command(repo, 'commit', '-q', '-m', message);
  return command(repo, 'rev-parse', 'HEAD');
}
function makeScenario(options = {}) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'tdr-pr-admission-'));
  const source = path.join(tmp, 'source');
  fs.mkdirSync(source, { recursive: true });
  command(source, 'init', '-q', '-b', 'main');
  command(source, 'config', 'user.name', 'TDR QA');
  command(source, 'config', 'user.email', 'qa@example.invalid');

  for (const item of ['AGENTS.md', 'CLAUDE.md',
    'docs/portfolio/TDR_MASTER_ROADMAP_V1.md',
    'docs/portfolio/portfolio.plan.json']) {
    const to = path.join(source, item);
    fs.mkdirSync(path.dirname(to), { recursive: true });
    fs.copyFileSync(path.join(root, item), to);
  }
  if (options.rename) {
    const from = path.join(source, 'lib/analysis/old.txt');
    fs.mkdirSync(path.dirname(from), { recursive: true });
    fs.writeFileSync(from, 'rename-me\n');
  }
  const base = commit(source, 'trusted base');
  if (options.rename) {
    fs.mkdirSync(path.join(source, 'app'), { recursive: true });
    command(source, 'mv', 'lib/analysis/old.txt', 'app/old.txt');
  } else {
    const to = path.join(source, 'lib/analysis/current.txt');
    fs.mkdirSync(path.dirname(to), { recursive: true });
    fs.writeFileSync(to, 'candidate data only\n');
  }
  if (options.managed) {
    const packet = path.join(source, '.tdr/enforcer-task.json');
    fs.mkdirSync(path.dirname(packet), { recursive: true });
    fs.writeFileSync(packet, JSON.stringify({
      schema: 'tdr.task-packet.v1', task_id: 'SYNTHETIC-INTEGRATION',
      roadmap_version: '1.0', base_sha: base,
      owner_authorized: false, allowed_paths: ['lib/analysis/**'],
      required_tests: ['node --test'], dependencies: [], execution_mode: 'OFFLINE',
    }));
  }
  const head = commit(source, 'candidate head');
  const policy = path.join(tmp, 'policy');
  const candidate = path.join(tmp, 'candidate');
  command(tmp, 'clone', '-q', source, policy);
  command(tmp, 'clone', '-q', source, candidate);
  command(policy, 'checkout', '--detach', '-q', base);
  command(candidate, 'checkout', '--detach', '-q', head);
  const event = path.join(tmp, 'event.json');
  fs.writeFileSync(event, JSON.stringify({
    repository: { full_name: 'smgkikikiki-cloud/TDR' },
    pull_request: { number: 206, base: { sha: base, ref: 'main' },
      head: { sha: head, ref: options.managed ? 'enforcer/test' : 'feat/manual' } },
  }));
  return { tmp, base, head, policy, candidate, event };
}
function inspect(scenario) {
  try {
    const output = execFileSync(process.execPath, [cli,
      '--event', scenario.event, '--policy-root', scenario.policy,
      '--candidate-root', scenario.candidate
    ], { cwd: root, encoding: 'utf8', timeout: 15000, stdio: ['ignore', 'pipe', 'pipe'] });
    return { exit: 0, report: JSON.parse(output) };
  } catch (error) {
    return { exit: error.status, report: JSON.parse(error.stdout.toString('utf8')) };
  }
}
function withScenario(opts, fn) {
  const x = makeScenario(opts);
  try { fn(x); } finally { fs.rmSync(x.tmp, { recursive: true, force: true }); }
}

test('real Git base/head and diff produce an unmanaged audit, never authorization', () => {
  withScenario({}, x => {
    const { exit, report } = inspect(x);
    assert.equal(exit, 0, JSON.stringify(report.errors));
    assert.equal(report.ok, true);
    assert.equal(report.admission, 'UNMANAGED_AUDIT_ONLY');
    assert.equal(report.enforcerAuthorized, false);
    assert.deepEqual(report.changedFiles, ['lib/analysis/current.txt']);
    assert.equal(report.baseSha, x.base);
    assert.equal(report.headSha, x.head);
  });
});
test('real Git rename exposes BOTH old and new names to the inspector', () => {
  withScenario({ rename: true }, x => {
    const { report } = inspect(x);
    assert.equal(report.admission, 'UNMANAGED_AUDIT_ONLY');
    assert.deepEqual(report.changedFiles,
      ['app/old.txt', 'lib/analysis/old.txt']);
  });
});
test('real Git managed task is refused with canonical execution disabled', () => {
  withScenario({ managed: true }, x => {
    const { exit, report } = inspect(x);
    assert.equal(exit, 1);
    assert.equal(report.ok, false);
    assert.equal(report.admission, 'DENIED');
    assert.equal(report.enforcerAuthorized, false);
    assert.ok(report.errors.includes('ENFORCER_DISABLED_IN_TRUSTED_BASE'));
    assert.ok(report.errors.includes('TRUSTED_BASE_TASK_APPROVAL_MISSING_OR_CHANGED'));
  });
});
test('real Git checkout mismatch fails closed before inspecting candidate data', () => {
  withScenario({}, x => {
    const event = JSON.parse(fs.readFileSync(x.event, 'utf8'));
    event.pull_request.head.sha = 'f'.repeat(40);
    fs.writeFileSync(x.event, JSON.stringify(event));
    assert.throws(() => execFileSync(process.execPath, [cli,
      '--event', x.event, '--policy-root', x.policy,
      '--candidate-root', x.candidate], {
      cwd: root, timeout: 15000, stdio: ['ignore', 'pipe', 'pipe'],
    }), { status: 1 });
  });
});
