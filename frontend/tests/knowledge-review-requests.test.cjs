const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const ts = require('../node_modules/typescript');
const component = fs.readFileSync(path.join(__dirname, '../src/lib/KnowledgeReview.svelte'), 'utf8');
const script = component.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
const tree = ts.createSourceFile('KnowledgeReview.ts', script, ts.ScriptTarget.Latest, true);
const functions = ts.transpileModule(tree.statements.filter(node => ts.isFunctionDeclaration(node)).map(node => node.getText(tree)).join('\n'), {compilerOptions: {target: ts.ScriptTarget.ES2022}}).outputText;

function harness() {
  const requests = [], timers = [];
  const context = vm.createContext({AbortController, setTimeout(fn) {timers.push(fn); return timers.length;}, clearTimeout() {}, fetch(url, options) {
    let resolve, reject;
    const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
    requests.push({url, options, resolve, reject}); return promise;
  }});
  vm.runInContext(`let endpoint='/admin/api/knowledge-review?tenant=FIRST',tenant='FIRST',sequence=0,controller=null,report=null,busy=false,error='';
    ${functions}
    globalThis.subject={refresh,dispose,state(){return {report,busy,error};}};`, context);
  return {subject: context.subject, requests, timers};
}
function reply(request, tenant = 'FIRST', ok = true) {
  request.resolve({ok, json: async () => ({tenant, issues: [], counts: {}, complete: true})});
}

test('knowledge review is requested on demand without model, mutation or third-party calls', async () => {
  const {subject, requests} = harness();
  assert.equal(requests.length, 0);
  const run = subject.refresh();
  assert.equal(requests[0].url, '/admin/api/knowledge-review?tenant=FIRST');
  assert.equal(requests[0].options.credentials, 'same-origin');
  assert.equal(requests[0].options.cache, 'no-store');
  assert.equal(requests[0].options.method, undefined);
  reply(requests[0]); await run;
  assert.equal(subject.state().report.tenant, 'FIRST');
});
test('leaving a business aborts the read and discards a late report', async () => {
  const {subject, requests} = harness();
  const run = subject.refresh(); subject.dispose();
  assert.equal(requests[0].options.signal.aborted, true);
  reply(requests[0]); await run;
  assert.equal(subject.state().report, null);
});
test('a stale read or its timer cannot overwrite or abort the current review', async () => {
  const {subject, requests, timers} = harness();
  const old = subject.refresh(); const current = subject.refresh();
  timers[0]();
  assert.equal(requests[1].options.signal.aborted, false);
  reply(requests[1]); await current;
  reply(requests[0], 'OTHER'); await old;
  assert.equal(subject.state().report.tenant, 'FIRST');
  assert.equal(subject.state().error, '');
});
test('a wrong-tenant or rejected report is not displayed', async () => {
  for (const [tenant, ok] of [['OTHER', true], ['FIRST', false]]) {
    const {subject, requests} = harness(); const run = subject.refresh();
    reply(requests[0], tenant, ok); await run;
    assert.equal(subject.state().report, null);
    assert.match(subject.state().error, /could not load/);
  }
});
test('network failure clears busy state and exposes no error payload', async () => {
  const {subject, requests} = harness(); const run = subject.refresh();
  requests[0].reject(new Error('PRIVATE_SERVER_PATH')); await run;
  assert.equal(subject.state().busy, false);
  assert.doesNotMatch(subject.state().error, /PRIVATE/);
});
