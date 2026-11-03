const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const ts=require('../node_modules/typescript');
const source=fs.readFileSync(path.join(__dirname,'../src/lib/PlatformOffers.svelte'),'utf8').match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
const tree=ts.createSourceFile('PlatformOffers.ts',source,ts.ScriptTarget.Latest,true);
const functions=ts.transpileModule(tree.statements.filter(ts.isFunctionDeclaration).map(node=>node.getText(tree)).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
function harness(){
  const requests=[];
  const scope=vm.createContext({AbortController,setTimeout,clearTimeout,fetch(url,options){
    let resolve;const promise=new Promise(yes=>resolve=yes);requests.push({url,options,resolve});return promise;
  }});
  vm.runInContext(`let tenant='VERTEX',csrf='synthetic-csrf',apiPrefix='',canManage=true;
    let available=null,loading=false,busy='',status='',error=false,disposed=false;
    let settings={setup_enabled:true,highstreet_enabled:true},revision='${'a'.repeat(64)}';
    let referral={enabled:true,percent:40,joining_setup_percent:100};const controllers=new Set();
    ${functions}
    globalThis.subject={load,toggle,toggleReferral,
      activate(){available=true;},readOnly(){canManage=false;},
      dispose(){disposed=true;for(const c of controllers)c.abort();},
      state(){return {available,loading,busy,status,error,settings,revision,referral};}};`,scope);
  return {subject:scope.subject,requests};
}
function respond(row,data,status=200){row.resolve({ok:status<400,status,json:async()=>data});}
const data={available:true,settings:{setup_enabled:true,highstreet_enabled:true},revision:'a'.repeat(64),referral:{enabled:true,percent:40,joining_setup_percent:100}};

test('pause is revision-bound and cannot submit percentages or arbitrary campaign terms',async()=>{
  const {subject,requests}=harness();subject.activate();const pending=subject.toggle('setup_enabled');
  await subject.toggle('highstreet_enabled');assert.equal(requests.length,1);
  const row=requests[0];assert.equal(row.url,'/admin/api/platform-promotions?tenant=VERTEX');
  assert.equal(row.options.credentials,'same-origin');assert.equal(row.options.headers['X-CSRF-Token'],'synthetic-csrf');
  assert.deepEqual(JSON.parse(row.options.body),{revision:'a'.repeat(64),settings:{setup_enabled:false,highstreet_enabled:true}});
  assert.equal(subject.state().settings.setup_enabled,true,'status stays unchanged until server confirmation');
  respond(row,{...data,settings:{...data.settings,setup_enabled:false},revision:'b'.repeat(64)});await pending;
  assert.equal(subject.state().settings.setup_enabled,false);assert.equal(subject.state().revision,'b'.repeat(64));
  assert.match(subject.state().status,/paused for new claims/);
});

test('read-only operators cannot write either kind of offer',async()=>{
  const {subject,requests}=harness();subject.activate();subject.readOnly();
  await subject.toggle('setup_enabled');await subject.toggleReferral();assert.equal(requests.length,0);
});

test('stale revision retains the last confirmed state and does not display response details',async()=>{
  const {subject,requests}=harness();subject.activate();const pending=subject.toggle('setup_enabled');
  respond(requests[0],{error:'access_token=secret /private/db'},409);await pending;
  assert.equal(subject.state().settings.setup_enabled,true);assert.equal(subject.state().error,true);
  assert.match(subject.state().status,/changed.*Refresh/);assert.doesNotMatch(subject.state().status,/secret|private/);
});

test('late results cannot update an exited company',async()=>{
  const {subject,requests}=harness();const pending=subject.load();subject.dispose();
  assert.equal(requests[0].options.signal.aborted,true);respond(requests[0],data);await pending;
  assert.equal(subject.state().available,null);
});

test('referrals use the existing operator endpoint with only the enabled switch',async()=>{
  const {subject,requests}=harness();subject.activate();const pending=subject.toggleReferral();
  assert.equal(requests[0].url,'/billing/referrals/program?tenant=VERTEX');
  assert.deepEqual(JSON.parse(requests[0].options.body),{enabled:false});
  respond(requests[0],{...data.referral,enabled:false});await pending;
  assert.equal(subject.state().referral.enabled,false);assert.match(subject.state().status,/paused/);
});
