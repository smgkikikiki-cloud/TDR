import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
const root=process.cwd();
const checkPath=path.join(root,'scripts/check-data-infra-contract.mjs');
const paths=['AGENTS.md','CLAUDE.md','docs/portfolio/TDR_DATA_INFRA_COMPLETION_CONTRACT.md',
'docs/portfolio/data-infra.requirements.json','docs/portfolio/TDR_DATA_INFRA_ACCEPTANCE_LEDGER.json'];
const createFixture=()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'tdr-contract-'));
 for(const name of paths){const dest=path.join(dir,name);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.copyFileSync(path.join(root,name),dest)}
 return dir;
};
const run=(dir,base='')=>spawnSync(process.execPath,[checkPath],{encoding:'utf8',
 env:{...process.env,TDR_CHECK_ROOT:dir,TDR_CHECK_BASE:base}});
const replace=(dir,p,fn)=>{const f=path.join(dir,p);fs.writeFileSync(f,fn(fs.readFileSync(f,'utf8')))};
const ledger='docs/portfolio/TDR_DATA_INFRA_ACCEPTANCE_LEDGER.json';
const registry='docs/portfolio/data-infra.requirements.json';
test('untouched registry and open evidence ledger pass',()=>{
 const f=createFixture();assert.equal(run(f).status,0);
 fs.rmSync(f,{recursive:true,force:true});
});
test('false ACCEPTED without verified source + owner ref fails',()=>{
 const f=createFixture();replace(f,ledger,t=>{const x=JSON.parse(t);x.requirements['A-01'].status='ACCEPTED';return JSON.stringify(x)});
 const r=run(f);assert.equal(r.status,1);assert.match(r.stdout,/FALSE_ACCEPTED:A-01/);fs.rmSync(f,{recursive:true,force:true});
});
test('a missing locked requirement fails',()=>{
 const f=createFixture();replace(f,registry,t=>{const x=JSON.parse(t);x.requirements.pop();return JSON.stringify(x)});
 const r=run(f);assert.equal(r.status,1);assert.match(r.stdout,/REQUIREMENTS_CHANGED/);fs.rmSync(f,{recursive:true,force:true});
});
test('agent bootstrap cannot discard completion document',()=>{
 const f=createFixture();replace(f,'AGENTS.md',t=>t.replace('docs/portfolio/TDR_DATA_INFRA_COMPLETION_CONTRACT.md','docs/portfolio/other.md'));
 const r=run(f);assert.equal(r.status,1);assert.match(r.stdout,/MISSING_BOOTSTRAP/);fs.rmSync(f,{recursive:true,force:true});
});
test('PR cannot silently rewrite locked acceptance criteria',()=>{
 const base=createFixture(),f=createFixture();replace(f,registry,t=>t.replace('69 months lossless','6 months lossless'));
 const r=run(f,base);assert.equal(r.status,1);assert.match(r.stdout,/LOCKED_TARGETS_CHANGED/);
 fs.rmSync(base,{recursive:true,force:true});fs.rmSync(f,{recursive:true,force:true});
});
test('project cannot declare COMPLETE without owner signature',()=>{
 const f=createFixture();replace(f,ledger,t=>{const x=JSON.parse(t);x.overall_status='COMPLETE';return JSON.stringify(x)});
 const r=run(f);assert.equal(r.status,1);assert.match(r.stdout,/FALSE_PROJECT_COMPLETE/);fs.rmSync(f,{recursive:true,force:true});
});
