const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const ts=require('../node_modules/typescript');
const source=fs.readFileSync(path.join(__dirname,'../src/lib/EmailManagement.svelte'),'utf8');
const script=source.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
const tree=ts.createSourceFile('EmailManagement.ts',script,ts.ScriptTarget.Latest,true);
const functions=ts.transpileModule(tree.statements.filter(ts.isFunctionDeclaration).map(node=>node.getText(tree)).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
function harness(stage='request') {
  const calls=[];
  const context=vm.createContext({AbortController,fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({ok:true})};}});
  vm.runInContext(`let csrf='synthetic-csrf',apiPrefix='',email='new@example.test',currentPassword='synthetic-current-password',code='123456';
    let stage='${stage}',busy=false,disposed=false,error='',notice='',controller=null;
    const known=new Set();${functions}
    globalThis.subject={submit,state(){return {stage,currentPassword,code};},dispose(){disposed=true;}};`,context);
  return {subject:context.subject,calls};
}
test('email request authenticates the current password with CSRF and clears it',async()=>{
  const {subject,calls}=harness();await subject.submit();
  assert.equal(calls[0].url,'/auth/account/email');
  assert.deepEqual(JSON.parse(calls[0].options.body),{email:'new@example.test',current_password:'synthetic-current-password'});
  assert.equal(calls[0].options.headers['X-CSRF-Token'],'synthetic-csrf');
  assert.equal(calls[0].options.credentials,'same-origin');
  assert.equal(subject.state().stage,'verify');assert.equal(subject.state().currentPassword,'');
});
test('confirmation sends only a code, never an account or role selector',async()=>{
  const {subject,calls}=harness('verify');await subject.submit();
  assert.equal(calls[0].url,'/auth/account/email/confirm');
  assert.deepEqual(JSON.parse(calls[0].options.body),{code:'123456'});
  assert.equal(subject.state().stage,'done');assert.equal(subject.state().code,'');
});
test('leaving the account screen prevents further submissions',async()=>{
  const {subject,calls}=harness();subject.dispose();await subject.submit();assert.equal(calls.length,0);
});
