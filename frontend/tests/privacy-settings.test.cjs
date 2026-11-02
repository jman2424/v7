const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../node_modules/typescript');
const test = require('node:test');

function privacyForm(responseStatus = 200) {
  const component = fs.readFileSync(path.join(__dirname, '../src/lib/PrivacySettings.svelte'), 'utf8');
  const source = component.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1]
    .replace(/^\s*import .*;\s*$/gm, '').replace(/export let /g, 'let ');
  const requests = [];
  const context = vm.createContext({
    AbortController, dirty:false, onMount() {}, onDestroy() {},
    fetch: async (url, options) => {
      requests.push({url, ...options});
      return {ok: responseStatus === 200, status: responseStatus,
        json: async () => ({settings: JSON.parse(options.body).settings, revision:'next', draft:false, missing_details:[], write_allowed:true})};
    }
  });
  vm.runInContext(ts.transpileModule(source, {compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText, context);
  vm.runInContext(`tenant='BUSINESS_A';csrf='synthetic-csrf';canEdit=true;data={write_allowed:true,revision:'current'};
    settings={controller_name:'Synthetic Business',contact_email:'privacy@example.test',retention_days:null,retention_criteria:'',lawful_basis:'Respond to enquiries'};`, context);
  return {requests, run: code => vm.runInContext(code, context)};
}

test('privacy retention saves the numeric value produced by a number input', async () => {
  const form = privacyForm();
  await form.run('retention=30;save()');
  assert.equal(form.requests.length, 1);
  assert.equal(form.requests[0].url, '/admin/api/privacy?tenant=BUSINESS_A');
  assert.equal(form.requests[0].headers['X-CSRF-Token'], 'synthetic-csrf');
  assert.equal(JSON.parse(form.requests[0].body).settings.retention_days, 30);
  assert.equal(form.run('status'), 'Privacy settings saved.');
  assert.equal(form.run('busy'), false);
});

test('blank privacy retention stays undecided and conflict preserves the draft', async () => {
  const form = privacyForm(409);
  await form.run("retention='';save()");
  assert.equal(JSON.parse(form.requests[0].body).settings.retention_days, null);
  assert.match(form.run('error'), /changed in another session/);
  assert.equal(form.run('settings.controller_name'), 'Synthetic Business');
  assert.equal(form.run('busy'), false);
});

test('privacy writes respect read-only and pending-save controls', async () => {
  const form = privacyForm();
  await form.run('canEdit=false;save()');
  await form.run('canEdit=true;busy=true;save()');
  assert.equal(form.requests.length, 0);
});
