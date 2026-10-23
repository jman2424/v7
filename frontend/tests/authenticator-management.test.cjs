const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const ts=require('../node_modules/typescript');
const source=fs.readFileSync(path.join(__dirname,'../src/lib/AuthenticatorManagement.svelte'),'utf8');
const script=source.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
const tree=ts.createSourceFile('AuthenticatorManagement.ts',script,ts.ScriptTarget.Latest,true);
const functions=ts.transpileModule(tree.statements.filter(ts.isFunctionDeclaration).map(n=>n.getText(tree)).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
function harness(fetcher) {
  const calls=[],timers=[];
  const context=vm.createContext({AbortController,setTimeout(fn,ms){timers.push({fn,ms});return 1;},clearTimeout(){},
    fetch:async(url,options)=>{calls.push({url,options});return fetcher ? fetcher() : {ok:true,json:async()=>({setup_key:'ABCDEFGHIJKLMNOP234567',qr_image:'data:image/svg+xml;base64,synthetic'})};}});
  vm.runInContext(`let csrf='synthetic-csrf',apiPrefix='',open=true,busy=false,disposed=false;
    let password='synthetic-password',code='123456',setupKey='',qrImage='',error='',controller=null,expiry;
    ${functions}
    globalThis.subject={reveal,close,state(){return {password,code,setupKey,qrImage,error,open};}};`,context);
  return {subject:context.subject,calls,timers};
}
test('another phone requires authenticated CSRF-protected step-up and no secret-bearing URL',async()=>{
  const {subject,calls,timers}=harness();await subject.reveal();
  assert.equal(calls[0].url,'/auth/mfa/add-device');
  assert.equal(calls[0].options.method,'POST');assert.equal(calls[0].options.credentials,'same-origin');
  assert.equal(calls[0].options.headers['X-CSRF-Token'],'synthetic-csrf');
  assert.equal(calls[0].options.cache,'no-store');
  assert.deepEqual(JSON.parse(calls[0].options.body),{current_password:'synthetic-password',code:'123456'});
  assert.equal(subject.state().password,'');assert.equal(subject.state().code,'');
  assert.equal(subject.state().setupKey,'ABCDEFGHIJKLMNOP234567');
  assert.equal(timers[0].ms,120000);timers[0].fn();assert.equal(subject.state().setupKey,'');
});
test('cancelled request cannot redisplay the enrollment after leaving setup',async()=>{
  let resolve;
  const {subject}=harness(()=>new Promise(r=>{resolve=r;}));
  const pending=subject.reveal();subject.close();
  resolve({ok:true,json:async()=>({setup_key:'ABCDEFGHIJKLMNOP234567',qr_image:'data:image/svg+xml;base64,synthetic'})});
  await pending;assert.equal(subject.state().setupKey,'');assert.equal(subject.state().open,false);
});
test('step-up failure clears credentials and never shows a setup key',async()=>{
  const {subject}=harness(()=>({ok:false,status:401,json:async()=>({error:'verification_failed'})}));
  await subject.reveal();assert.equal(subject.state().setupKey,'');assert.equal(subject.state().password,'');
  assert.match(subject.state().error,/fresh code/);
});
