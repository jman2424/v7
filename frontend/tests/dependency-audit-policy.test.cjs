const test = require('node:test');
const assert = require('node:assert/strict');

async function fixture() {
  const policy = await import('../../scripts/audit-console-dependencies.mjs');
  const audit = {auditReportVersion:2, vulnerabilities:{
    picomatch:{name:'picomatch',nodes:['node_modules/picomatch'],via:[{name:'picomatch',url:policy.advisory}]},
    vite:{name:'vite',nodes:['node_modules/vite'],via:['picomatch']}
  }};
  const lock = {packages:{'node_modules/picomatch':{dev:true,version:'4.0.7'},'node_modules/vite':{dev:true}}};
  return {policy,audit,lock,now:new Date('2026-11-18T12:00:00Z')};
}

test('only the disclosed build-only advisory and its transitive findings are covered',async()=>{
  const {policy,audit,lock,now}=await fixture();
  assert.equal(policy.reviewAudit(audit,lock,now).exceptions,2);
  audit.vulnerabilities.picomatch.via.push({name:'picomatch',url:'https://github.com/advisories/GHSA-other'});
  assert.throws(()=>policy.reviewAudit(audit,lock,now),/outside/);
});

test('runtime dependencies, changed versions and expired exceptions fail closed',async()=>{
  const {policy,audit,lock,now}=await fixture();
  lock.packages['node_modules/vite'].dev=false;
  assert.throws(()=>policy.reviewAudit(audit,lock,now),/runtime/);
  lock.packages['node_modules/vite'].dev=true;
  lock.packages['node_modules/picomatch'].version='4.0.8';
  assert.throws(()=>policy.reviewAudit(audit,lock,now),/version/);
  lock.packages['node_modules/picomatch'].version='4.0.7';
  assert.throws(()=>policy.reviewAudit(audit,lock,new Date(policy.expires)),/expired/);
});

test('failed audit, malformed reports and cyclic advisory chains never pass',async()=>{
  const {policy,audit,lock,now}=await fixture();
  assert.throws(()=>policy.reviewAudit({error:{code:'network'}},lock,now),/unsupported/);
  assert.throws(()=>policy.reviewAudit({},lock,now),/unsupported/);
  audit.vulnerabilities.picomatch.via=['vite'];
  assert.throws(()=>policy.reviewAudit(audit,lock,now),/outside/);
  assert.equal(policy.reviewAudit({auditReportVersion:2,vulnerabilities:{}},lock,now).exceptions,0);
});
