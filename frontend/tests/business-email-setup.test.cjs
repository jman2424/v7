const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const ts=require('../node_modules/typescript');
const source=fs.readFileSync(path.join(__dirname,'../src/lib/BusinessEmailSetup.svelte'),'utf8').match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
const tree=ts.createSourceFile('Setup.ts',source,ts.ScriptTarget.Latest,true);
const functions=ts.transpileModule(tree.statements.filter(ts.isFunctionDeclaration).map(node=>node.getText(tree)).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
function harness(){
  const requests=[];
  const context=vm.createContext({AbortController,fetch(url,options){
    let resolve;const promise=new Promise(yes=>resolve=yes);requests.push({url,options,resolve});return promise;
  }});
  vm.runInContext(`let tenant='ONE',csrf='synthetic-csrf',canManage=true,apiPrefix='';
    let address='',provider='hosted_email',revision='',state='not_started',loading=true,busy=false,disposed=false;
    let storageAvailable=false,cleanupCounts=null,forwardTo=[],message='',error=false;const controllers=new Set();
    ${functions}
    globalThis.subject={load,save,edit(value){address=value;},readOnly(){canManage=false;},
      dispose(){disposed=true;for(const c of controllers)c.abort();},
      state(){return {address,revision,state,busy,message,error};}};`,context);
  return {subject:context.subject,requests};
}
function respond(request,data,ok=true){request.resolve({ok,json:async()=>data});}
const data={settings:{address:'help@company.example',provider:'google_workspace'},revision:'revision-one',state:'requested',storage_available:false,cleanup_counts:null,forward_to:[]};
test('setup saves only the scoped address and provider with CSRF and revision',async()=>{
  const {subject,requests}=harness();const load=subject.load();respond(requests[0],data);await load;
  assert.equal(requests[0].options.headers['Content-Type'],undefined);
  const save=subject.save();await subject.save();assert.equal(requests.length,2);
  const request=requests[1];assert.equal(request.url,'/admin/api/business-email-setup?tenant=ONE');
  assert.equal(request.options.credentials,'same-origin');assert.equal(request.options.headers['X-CSRF-Token'],'synthetic-csrf');
  assert.deepEqual(JSON.parse(request.options.body),{revision:'revision-one',settings:{address:'help@company.example',provider:'google_workspace',purpose:'support'}});
  respond(request,data);await save;assert.match(subject.state().message,/must verify/);
});
test('leaving a company aborts setup and discards its late response',async()=>{
  const {subject,requests}=harness();const load=subject.load();subject.dispose();
  assert.ok(requests[0].options.signal.aborted);respond(requests[0],data);await load;
  assert.equal(subject.state().address,'');
});
test('read-only users cannot submit setup and provider details are never displayed',async()=>{
  const {subject,requests}=harness();subject.readOnly();await subject.save();assert.equal(requests.length,0);
  const load=subject.load();respond(requests[0],{error:'PRIVATE_SECRET'},false);await load;
  assert.equal(subject.state().error,true);assert.doesNotMatch(subject.state().message,/PRIVATE_SECRET/);
});
