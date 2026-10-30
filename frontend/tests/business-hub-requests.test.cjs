const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const ts=require('../node_modules/typescript');
const component=fs.readFileSync(path.join(__dirname,'../src/lib/BusinessHub.svelte'),'utf8');
const script=component.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
const tree=ts.createSourceFile('BusinessHub.ts',script,ts.ScriptTarget.Latest,true);
const functions=ts.transpileModule(tree.statements.filter(ts.isFunctionDeclaration).map(node=>node.getText(tree)).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
const constants=ts.transpileModule(tree.statements.filter(node=>ts.isVariableStatement(node)&&node.declarationList.declarations.some(row=>row.name.getText(tree)==='errorMessages')).map(node=>node.getText(tree)).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
function harness(){
  const requests=[];
  const context=vm.createContext({AbortController,fetch(url,options){
    let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});
    requests.push({url,options,resolve,reject});return promise;
  }});
  vm.runInContext(`let tenant='FIRST',csrf='csrf-test',apiPrefix='',isPlatform=false,canManage=true;
    let settings=null,grants={},readiness={},workerEnabled=false,operations=[],drafts={},status='',error=false,loading=false,saving=false,busyId='',disposed=false,generation=0;
    let actionFor='',actionType='callback',actionName='',actionContact='',actionDetails='',actionSlot='',actionConsent=false;
    const controllers=new Set();${constants}${functions}
    globalThis.subject={load,decide,performAction,prepareAction,
      dispose(){disposed=true;generation++;for(const controller of controllers)controller.abort();},
      draft(id,text){drafts[id]=text;},consent(value){actionConsent=value;},
      state(){return {operations,settings,status,error,busyId,loading};}};`,context);
  return {subject:context.subject,requests};
}
function respond(request,data,ok=true){request.resolve({ok,json:async()=>data});}
function config(marker){return {settings:{marker},grants:{},channels:{},worker_enabled:false};}
test('late hub responses are discarded after leaving a business',async()=>{
  const {subject,requests}=harness();const run=subject.load();subject.dispose();
  assert.equal(requests[0].options.headers['Content-Type'],undefined);
  assert.ok(requests.every(row=>row.options.signal.aborted));
  respond(requests[0],config('old'));respond(requests[1],{operations:[{id:'foreign'}]});await run;
  assert.equal(subject.state().settings,null);assert.equal(subject.state().operations.length,0);
});
test('an older hub refresh cannot overwrite current drafts or activity',async()=>{
  const {subject,requests}=harness();const old=subject.load(),current=subject.load();
  respond(requests[2],config('new'));respond(requests[3],{operations:[{id:'current',reply:'Fresh draft'}]});await current;
  respond(requests[0],config('old'));respond(requests[1],{operations:[{id:'old',reply:'Stale draft'}]});await old;
  assert.equal(subject.state().settings.marker,'new');assert.equal(subject.state().operations[0].id,'current');
});
test('approval is version-bound, uses CSRF and cannot replace recipient fields',async()=>{
  const {subject,requests}=harness();subject.draft('job','Approved body');
  const row={id:'job',version:4,source_address:'visitor@example.net'};const run=subject.decide(row,'approve');
  const request=requests[0],body=JSON.parse(request.options.body);
  assert.equal(request.url,'/admin/api/business-operations/job/decision?tenant=FIRST');
  assert.equal(request.options.headers['X-CSRF-Token'],'csrf-test');
  assert.equal(request.options.credentials,'same-origin');
  assert.deepEqual(body,{decision:'approve',version:4,reply:'Approved body'});
  await subject.decide(row,'approve');assert.equal(requests.length,1);
  respond(request,{operation:{...row,state:'approved'}});await run;
});
test('business actions need explicit consent and duplicate submits are suppressed',async()=>{
  const {subject,requests}=harness();const row={id:'job',version:5,source_address:'visitor@example.net'};
  subject.prepareAction(row);await subject.performAction(row);assert.equal(requests.length,0);
  subject.consent(true);const run=subject.performAction(row);await subject.performAction(row);
  assert.equal(requests.length,1);const body=JSON.parse(requests[0].options.body);
  assert.equal(body.version,5);assert.equal(body.action.consent,true);
  assert.equal(body.action.contact,'visitor@example.net');assert.equal(body.action.idempotency_key,undefined);
  respond(requests[0],{operation:{...row,state:'completed'},outcome:{status:'requested',reference:'reference'}});await run;
  assert.match(subject.state().status,/Request saved/);assert.doesNotMatch(subject.state().status,/confirmed/i);
});
test('unexpected server errors expose no internal response detail',async()=>{
  const {subject,requests}=harness();const run=subject.load();
  respond(requests[0],{error:'PRIVATE_PROVIDER_DETAIL'},false);respond(requests[1],{operations:[]});await run;
  assert.equal(subject.state().error,true);assert.doesNotMatch(subject.state().status,/PRIVATE/);
});
