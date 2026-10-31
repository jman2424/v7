const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const ts=require('../node_modules/typescript');
const source=fs.readFileSync(path.join(__dirname,'../src/lib/AgentModules.svelte'),'utf8').match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
const tree=ts.createSourceFile('Modules.ts',source,ts.ScriptTarget.Latest,true);
const functions=ts.transpileModule(tree.statements.filter(ts.isFunctionDeclaration).map(row=>row.getText(tree)).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
const constants=ts.transpileModule(tree.statements.filter(row=>ts.isVariableStatement(row)&&row.declarationList.declarations.some(item=>item.name.getText(tree)==='failures')).map(row=>row.getText(tree)).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
function harness(){
  const requests=[];
  const context=vm.createContext({AbortController,fetch(url,options){
    let resolve;const promise=new Promise(yes=>resolve=yes);requests.push({url,options,resolve});return promise;
  }});
  vm.runInContext(`let tenant='ONE',csrf='synthetic-csrf',isPlatform=false,canManage=true,apiPrefix='';
    const onReady=()=>{},onSaved=()=>{};
    let modules=[],grants={},enabled={},revision='',initialized=false,loading=true,busy=false,disposed=false,message='',error=false;
    const controllers=new Set();${constants}${functions}
    globalThis.subject={load,save,operator(){isPlatform=true;},readOnly(){canManage=false;},
      dispose(){disposed=true;for(const controller of controllers)controller.abort();},
      state(){return {revision,enabled,grants,modules,message,error};}};`,context);
  return {subject:context.subject,requests};
}
const data={initialized:true,revision:'revision-one',modules:[{id:'quote',granted:true,enabled:true,available:true}]};
function respond(request,value,ok=true){request.resolve({ok,json:async()=>value});}
test('owner save is revision-bound, tenant-scoped and cannot change grants',async()=>{
  const {subject,requests}=harness();const load=subject.load();respond(requests[0],data);await load;
  assert.equal(requests[0].options.headers['Content-Type'],undefined);
  const save=subject.save('enabled');await subject.save('enabled');assert.equal(requests.length,2);
  const request=requests[1];assert.equal(request.url,'/admin/api/agent-modules?tenant=ONE');
  assert.equal(request.options.credentials,'same-origin');assert.equal(request.options.headers['X-CSRF-Token'],'synthetic-csrf');
  assert.deepEqual(JSON.parse(request.options.body),{revision:'revision-one',enabled:{quote:true}});
  respond(request,data);await save;
});
test('owner cannot invoke operator grant save; read-only users cannot save switches',async()=>{
  const {subject,requests}=harness();await subject.save('grants');assert.equal(requests.length,0);
  subject.readOnly();await subject.save('enabled');assert.equal(requests.length,0);
});
test('late company responses are aborted and discarded',async()=>{
  const {subject,requests}=harness();const load=subject.load();subject.dispose();
  assert.ok(requests[0].options.signal.aborted);respond(requests[0],data);await load;
  assert.equal(subject.state().revision,'');assert.equal(subject.state().modules.length,0);
});
test('revoked grants are not resubmitted as enabled settings',async()=>{
  const {subject,requests}=harness();const load=subject.load();
  respond(requests[0],{...data,modules:[{...data.modules[0],granted:false}]});await load;
  const save=subject.save('enabled');assert.deepEqual(JSON.parse(requests[1].options.body).enabled,{quote:false});
  respond(requests[1],data);await save;
});
test('provider/internal failure detail never becomes a UI error',async()=>{
  const {subject,requests}=harness();const load=subject.load();respond(requests[0],{error:'PRIVATE_SECRET'},false);await load;
  assert.equal(subject.state().error,true);assert.doesNotMatch(subject.state().message,/PRIVATE_SECRET/);
});
