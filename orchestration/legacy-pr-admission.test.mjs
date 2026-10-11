import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { evaluateLegacy } from './legacy-pr-admission.mjs';

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const cliPath = path.join(moduleDir, 'legacy-pr-admission.mjs');
const SHA1 = 'a'.repeat(40), SHA2 = 'b'.repeat(40);
function event(ref = 'feat/old-branch') {
  return { repository: { full_name: 'smgkikikiki-cloud/TDR' },
    pull_request: { number: 201, base: { ref: 'main', sha: SHA1 },
      head: { ref, sha: SHA2 } } };
}
const change = p => [{ kind: 'M', paths: [p] }];

test('legacy normal PR is explicitly audit-only, never task authorization', () => {
  const r = evaluateLegacy({event:event(),changes:change('lib/feature.ts')});
  assert.equal(r.ok,true); assert.equal(r.admission,'LEGACY_UNMANAGED_AUDIT_ONLY');
  assert.equal(r.enforcerAuthorized,false);
});
test('historical PR 201 changing WORK_STATE stays audit-only', () => {
  const r = evaluateLegacy({event:event(),changes:change('docs/WORK_STATE.md')});
  assert.equal(r.ok,true);assert.equal(r.enforcerAuthorized,false);
});
test('historical PR 203 catalog code stays audit-only', () => {
  const r=evaluateLegacy({event:event('codex/vehicle-catalog-maintainer'),
    changes:change('automotive/vehicle_master/catalog_maintainer/planner.py')});
  assert.equal(r.admission,'LEGACY_UNMANAGED_AUDIT_ONLY');
});
test('managed branch denied without a trusted base authorizer', () => {
  const r=evaluateLegacy({event:event('enforcer/task'),changes:change('lib/feature.ts')});
  assert.ok(r.errors.includes('LEGACY_BASE_MANAGED_TASK_DENIED'));
});
test('packet or deleted packet denied even on ordinary branch', () => {
  const a=evaluateLegacy({event:event(),changes:change('lib/a.ts'),hasPacket:true});
  const b=evaluateLegacy({event:event(),changes:[{kind:'D',paths:['.tdr/enforcer-task.json']}]});
  assert.equal(a.ok,false);assert.equal(b.ok,false);
});
test('candidate governance, workflow and production policy changes denied', () => {
  for(const file of ['AGENTS.md','CLAUDE.md','.github/workflows/enforcer-pr-admission.yml',
    'orchestration/preflight.mjs','docs/portfolio/portfolio.plan.json',
    'docs/market-track/ROADMAP.md','docs/vehicle-db/VEHICLE_DB_V3.md',
    'supabase/migrations/v999.sql','.env.local']) {
    const r=evaluateLegacy({event:event(),changes:change(file)});
    assert.ok(r.errors.includes('LEGACY_BASE_GOVERNANCE_CHANGE_DENIED:'+file),file);
  }
});
test('renames into and out of protected paths are both denied', () => {
  for(const paths of [['lib/old.ts','orchestration/preflight.mjs'],['AGENTS.md','lib/old.ts']]){
    const r=evaluateLegacy({event:event(),changes:[{kind:'R',paths}]});
    assert.equal(r.ok,false);
  }
});
test('invalid GitHub metadata or empty diff never passes', () => {
  const e=event();e.repository.full_name='attacker/TDR';e.pull_request.base.sha='bad';
  assert.equal(evaluateLegacy({event:e,changes:change('lib/x')}).ok,false);
  assert.equal(evaluateLegacy({event:event(),changes:[]}).ok,false);
  assert.equal(evaluateLegacy({event:event(),changes:change('../bad')}).ok,false);
});

function git(cwd,...args) {
  return execFileSync('git',args,{cwd,encoding:'utf8',timeout:15000,
    env:{...process.env,GIT_CONFIG_NOSYSTEM:'1'},
    stdio:['ignore','pipe','pipe']}).trim();
}
function scenario(kind) {
  const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'tdr-legacy-'));
  const source=path.join(tmp,'source');fs.mkdirSync(source);
  git(source,'init','-q','-b','main');
  git(source,'config','user.name','TDR QA');
  git(source,'config','user.email','qa@example.invalid');
  const put=(p,s)=>{const file=path.join(source,p);
    fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,s);};
  put('AGENTS.md','old instructions\n');
  put('docs/WORK_STATE.md','old state\n');
  put('lib/old.txt','rename source\n');
  git(source,'add','-A');git(source,'commit','-q','-m','historical base');
  const base=git(source,'rev-parse','HEAD');
  if(kind==='normal')put('lib/new.txt','feature\n');
  else if(kind==='workstate')put('docs/WORK_STATE.md','updated status\n');
  else if(kind==='managed')put('.tdr/enforcer-task.json','{"owner_authorized":true}\n');
  else if(kind==='tamper')put('AGENTS.md','malicious instructions\n');
  else if(kind==='rename'){
    fs.mkdirSync(path.join(source,'orchestration'),{recursive:true});
    git(source,'mv','lib/old.txt','orchestration/preflight.mjs');
  } else throw new Error('unknown fixture');
  git(source,'add','-A');git(source,'commit','-q','-m','candidate');
  const head=git(source,'rev-parse','HEAD');
  const policy=path.join(tmp,'policy'),candidate=path.join(tmp,'candidate');
  git(tmp,'clone','-q',source,policy);git(tmp,'clone','-q',source,candidate);
  git(policy,'checkout','-q','--detach',base);
  git(candidate,'checkout','-q','--detach',head);
  const eventFile=path.join(tmp,'event.json');
  const e={repository:{full_name:'smgkikikiki-cloud/TDR'},
    pull_request:{number:201,base:{ref:'main',sha:base},
      head:{ref:'feat/old-branch',sha:head}}};
  fs.writeFileSync(eventFile,JSON.stringify(e));
  return {tmp,eventFile,policy,candidate,event:e};
}
function run(kind,mutate) {
  const x=scenario(kind);
  try {
    if(mutate)mutate(x);
    try {
      const s=execFileSync(process.execPath,[cliPath,'--event',x.eventFile,
        '--policy-root',x.policy,'--candidate-root',x.candidate],
        {encoding:'utf8',timeout:15000,stdio:['ignore','pipe','pipe']});
      return {exit:0,result:JSON.parse(s)};
    }catch(err){
      return {exit:err.status,result:JSON.parse(String(err.stdout||err.stderr))};
    }
  }finally{fs.rmSync(x.tmp,{recursive:true,force:true});}
}
test('integration: old Git base + normal head without scripts audits successfully',()=>{
  const r=run('normal');assert.equal(r.exit,0,JSON.stringify(r.result.errors));
  assert.equal(r.result.admission,'LEGACY_UNMANAGED_AUDIT_ONLY');
  assert.equal(r.result.enforcerAuthorized,false);
});
test('integration: PR201-like WORK_STATE edit remains audit-only',()=>{
  const r=run('workstate');assert.equal(r.exit,0);assert.equal(r.result.enforcerAuthorized,false);
});
test('integration: unauthorized packet is denied and exits nonzero',()=>{
  const r=run('managed');assert.equal(r.exit,1);
  assert.ok(r.result.errors.includes('LEGACY_BASE_MANAGED_TASK_DENIED'));
});
test('integration: tampered candidate governance file denied',()=>{
  const r=run('tamper');assert.equal(r.exit,1);
  assert.ok(r.result.errors.includes('LEGACY_BASE_GOVERNANCE_CHANGE_DENIED:AGENTS.md'));
});
test('integration: rename into central Enforcer path is denied',()=>{
  const r=run('rename');assert.equal(r.exit,1);
  assert.ok(r.result.errors.includes('LEGACY_BASE_GOVERNANCE_CHANGE_DENIED:orchestration/preflight.mjs'));
});
test('integration: fake GitHub SHA is rejected before candidate inspection',()=>{
  const r=run('normal',x=>{
    x.event.pull_request.head.sha='f'.repeat(40);
    fs.writeFileSync(x.eventFile,JSON.stringify(x.event));
  });
  assert.equal(r.exit,1);assert.ok(r.result.errors.includes('LEGACY_ADMISSION_INPUT_ERROR'));
});
