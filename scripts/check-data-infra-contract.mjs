import fs from 'node:fs';
import path from 'node:path';
const ROOT = process.env.TDR_CHECK_ROOT || process.cwd();
const BASE = process.env.TDR_CHECK_BASE || '';
const read = (r,p) => fs.readFileSync(path.join(r,p),'utf8');
const json = (r,p) => JSON.parse(read(r,p));
const contractPath = 'docs/portfolio/TDR_DATA_INFRA_COMPLETION_CONTRACT.md';
const specPath = 'docs/portfolio/data-infra.requirements.json';
const ledgerPath = 'docs/portfolio/TDR_DATA_INFRA_ACCEPTANCE_LEDGER.json';
const planPath = 'docs/portfolio/TDR_DATA_INFRA_EXECUTION_PLAN.md';
const ids = 'A-01 A-02 A-03 A-04 A-05 B-01 B-02 B-03 B-04 C-01 C-02 C-03 C-04 C-05 C-06 D-01 D-02 D-03 D-04 D-05 D-06 D-07 E-01 E-02 E-03 E-04 E-05 E-06 E-07'.split(' ');
const errors = [];
try {
 const spec=json(ROOT,specPath),ledger=json(ROOT,ledgerPath),doc=read(ROOT,contractPath);
 if(spec.contract_version!=='1.0.0'||spec.schema!=='tdr.data-infra.completion.v1')errors.push('BAD_CONTRACT_VERSION');
 if(JSON.stringify(spec.requirements.map(x=>x.id))!==JSON.stringify(ids))errors.push('REQUIREMENTS_CHANGED');
 if(JSON.stringify(spec.phases.map(x=>x.id))!==JSON.stringify(['A','B','C','D','E']))errors.push('PHASES_CHANGED');
 if(!doc.startsWith('# TDR Data Infrastructure — Locked Completion Contract v1.0.0'))errors.push('CONTRACT_MISSING');
 for(const r of spec.requirements){
  if(!r.title||!r.acceptance||!r.evidence_required||r.required_state!=='ACCEPTED'||r.phase!==r.id[0])errors.push('BAD_REQUIREMENT:'+r.id);
  if(!doc.includes('| '+r.id+' |'))errors.push('UNREFERENCED_REQUIREMENT:'+r.id);
 }
 for(const file of ['AGENTS.md','CLAUDE.md']){
  const source=read(ROOT,file);
  for(const pointer of [contractPath,specPath,planPath,ledgerPath])if(!source.includes(pointer))errors.push('MISSING_BOOTSTRAP:'+file+':'+pointer);
 }
 if(ledger.contract_version!=='1.0.0'||ledger.schema!=='tdr.data-infra.acceptance-ledger.v1')errors.push('BAD_LEDGER');
 if(JSON.stringify(Object.keys(ledger.requirements).sort())!==JSON.stringify([...ids].sort()))errors.push('LEDGER_IDS_CHANGED');
 const accepted=[];
 for(const id of ids){
  const state=ledger.requirements[id];
  if(!state)continue;
  if(!['OPEN','IN_PROGRESS','BLOCKED','EVIDENCED','ACCEPTED'].includes(state.status))errors.push('INVALID_STATUS:'+id);
  if(!Array.isArray(state.evidence)||!Array.isArray(state.blockers))errors.push('BAD_EVIDENCE_SHAPE:'+id);
  if(state.status==='EVIDENCED'&&!state.evidence.length)errors.push('EVIDENCE_REQUIRED:'+id);
  if(state.status==='ACCEPTED'){
   accepted.push(id);
   if(!/^[0-9a-f]{40}$/i.test(state.verified_commit||'')||!state.owner_acceptance_ref||
     !state.evidence.length||state.evidence.some(e=>!e.uri||!e.test))errors.push('FALSE_ACCEPTED:'+id);
  }
 }
 const final=accepted.length===ids.length&&ledger.owner_final_acceptance?.approval_ref&&
   /^[0-9a-f]{40}$/i.test(ledger.owner_final_acceptance?.ledger_commit||'');
 if(ledger.overall_status==='COMPLETE'&&!final)errors.push('FALSE_PROJECT_COMPLETE');
 if(!['INCOMPLETE','COMPLETE'].includes(ledger.overall_status))errors.push('BAD_PROJECT_STATUS');
 if(BASE&&fs.existsSync(path.join(BASE,specPath))){
  const prior=json(BASE,specPath);
  if(JSON.stringify(prior)!==JSON.stringify(spec))errors.push('LOCKED_TARGETS_CHANGED_REQUIRES_SEPARATE_OWNER_APPROVED_AMENDMENT');
  if(read(BASE,contractPath)!==doc)errors.push('LOCKED_CONTRACT_CHANGED_REQUIRES_SEPARATE_OWNER_APPROVED_AMENDMENT');
 }
 const changesFile=process.env.TDR_CHECK_DIFF_PATH;
 if(changesFile&&fs.existsSync(changesFile)&&process.env.GITHUB_EVENT_PATH){
  const candidate=process.env.TDR_CHECK_CANDIDATE_ROOT||ROOT;
  if(fs.existsSync(path.join(candidate,specPath))){
   const event=JSON.parse(fs.readFileSync(process.env.GITHUB_EVENT_PATH,'utf8'));
   const changed=fs.readFileSync(changesFile,'utf8').split(/\r?\n/).filter(Boolean);
   const scope=/^(AGENTS\.md|CLAUDE\.md|lib\/(ice-|price-|spec-)|scripts\/(ice-|price-|spec-)|app\/(member\/|admin\/ice-|api\/report\/)|automotive\/vehicle_master\/|supabase\/|docs\/portfolio\/(TDR_DATA_INFRA_|data-infra\.requirements)|\.github\/workflows\/data-infra-contract\.yml)/;
   if(event.pull_request&&changed.some(name=>scope.test(name))){
    const body=String(event.pull_request.body||'');
    for(const prefix of ['Contract-Version: 1.0.0','Requirement-IDs:','Acceptance-Tests:','Evidence-Plan:','Domain-Gate:']){
     if(!body.includes(prefix))errors.push('PR_TASK_HANDSHAKE_MISSING:'+prefix);
    }
    const match=body.match(/^Requirement-IDs:\s*(.+)$/m);
    const requested=match?match[1].split(',').map(x=>x.trim()).filter(Boolean):[];
    if(!requested.length||requested.some(x=>!ids.includes(x)))errors.push('PR_UNKNOWN_REQUIREMENT_IDS');
   }
  }
 }
 console.log(JSON.stringify({ok:!errors.length,requirements:ids.length,accepted:accepted.length,errors},null,2));
}catch(e){errors.push('CHECK_FAILED:'+e.message);console.error(errors.join('\n'))}
if(errors.length)process.exitCode=1;
