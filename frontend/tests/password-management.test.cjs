const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const ts = require('../node_modules/typescript');
const source = fs.readFileSync(path.join(__dirname, '../src/lib/PasswordManagement.svelte'), 'utf8');
const script = source.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
const tree = ts.createSourceFile('PasswordManagement.ts', script, ts.ScriptTarget.Latest, true);
const functions = ts.transpileModule(tree.statements.filter(ts.isFunctionDeclaration).map(node => node.getText(tree)).join('\n'), {compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
function harness(recovery=true) {
  const calls=[];
  const context=vm.createContext({AbortController,fetch:async(url,options)=>{
    calls.push({url,options});return {ok:true,json:async()=>({ok:true})};
  }});
  vm.runInContext(`let csrf='synthetic-csrf',tenant='ALPHA',email='owner@example.test',apiPrefix='',recovery=${recovery};
    let currentPassword='old-password-123',password='new-password-456',confirmation='new-password-456',code='123456';
    let stage='${recovery?'confirm':'request'}',busy=false,error='',notice='',controller=null;
    const messages=new Set();${functions}
    globalThis.subject={submit,state(){return {currentPassword,password,confirmation,code,stage,error};},mismatch(){confirmation='different';}};`,context);
  return {subject:context.subject,calls};
}
test('reset confirmation sends only code and password with CSRF and clears secrets',async()=>{
  const {subject,calls}=harness();await subject.submit();
  assert.equal(calls[0].url,'/auth/password/reset/confirm');
  assert.deepEqual(JSON.parse(calls[0].options.body),{code:'123456',password:'new-password-456'});
  assert.equal(calls[0].options.headers['X-CSRF-Token'],'synthetic-csrf');
  assert.equal(calls[0].options.credentials,'same-origin');
  assert.equal(subject.state().stage,'done');
  for(const name of ['currentPassword','password','confirmation','code'])assert.equal(subject.state()[name],'');
});
test('self change sends no tenant or account selector',async()=>{
  const {subject,calls}=harness(false);await subject.submit();
  assert.equal(calls[0].url,'/auth/password/change');
  assert.deepEqual(JSON.parse(calls[0].options.body),{current_password:'old-password-123',password:'new-password-456'});
});
test('mismatched passwords never send a request',async()=>{
  const {subject,calls}=harness();subject.mismatch();await subject.submit();
  assert.equal(calls.length,0);assert.equal(subject.state().error,'Passwords do not match.');
});
test('new account messages are translated into all supported non-English languages',()=>{
  const dictionary = require('../../dashboard/static/i18n/accounts.json');
  for(const language of ['es','fr','ar']) {
    assert.deepEqual(Object.keys(dictionary[language]).sort(),Object.keys(dictionary.es).sort());
    for(const [key,value] of Object.entries(dictionary[language])) assert.ok(value && value!==key,language+': '+key);
  }
});
