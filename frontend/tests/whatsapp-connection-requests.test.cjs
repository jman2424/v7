const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const ts = require('../node_modules/typescript');
const source = fs.readFileSync(path.join(__dirname, '../src/lib/WhatsAppConnection.svelte'), 'utf8');
const script = source.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
const tree = ts.createSourceFile('WhatsAppConnection.ts', script, ts.ScriptTarget.Latest, true);
const functions = ts.transpileModule(tree.statements.filter(ts.isFunctionDeclaration).map(node => node.getText(tree)).join('\n'), {compilerOptions: {target: ts.ScriptTarget.ES2022}}).outputText;
function harness() {
  const requests = [];
  const context = vm.createContext({AbortController, setTimeout, clearTimeout, fetch(url, options) {
    let resolve;
    const promise = new Promise(done => resolve = done);
    requests.push({url, options, resolve});
    return promise;
  }});
  vm.runInContext(`let tenant='ALPHA',apiPrefix='',controller,busy=false,error='',copied='',status=null,providerChosen=false,provider='meta';
    ${functions}
    globalThis.subject={load,abort(){controller.abort();},state(){return {status,error};}};`, context);
  return {subject: context.subject, requests};
}
const configuration = {providers: {meta: {configured: true, enabled: true}, twilio: {configured: false}}};
test('WhatsApp setup discards another company response', async () => {
  const {subject, requests} = harness();
  const pending = subject.load();
  assert.equal(requests[0].url, '/admin/api/integrations?tenant=ALPHA');
  assert.equal(requests[0].options.credentials, 'same-origin');
  requests[0].resolve({ok: true, json: async () => ({tenant: 'BETA', whatsapp: configuration})});
  await pending;
  assert.equal(subject.state().status, null);
  assert.ok(subject.state().error);
});
test('WhatsApp setup accepts its company and discards an aborted late response', async () => {
  const {subject, requests} = harness();
  let pending = subject.load();
  requests[0].resolve({ok: true, json: async () => ({tenant: 'ALPHA', whatsapp: configuration})});
  await pending;
  assert.equal(subject.state().status, configuration);
  pending = subject.load();
  subject.abort();
  requests[1].resolve({ok: true, json: async () => ({tenant: 'ALPHA', whatsapp: {...configuration, changed: true}})});
  await pending;
  assert.equal(subject.state().status, configuration);
});
