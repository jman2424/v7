const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const ts=require('../node_modules/typescript');
const component=fs.readFileSync(path.join(__dirname,'../src/lib/ModelPicker.svelte'),'utf8');
const script=component.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
const tree=ts.createSourceFile('ModelPicker.ts',script,ts.ScriptTarget.Latest,true);
const functions=ts.transpileModule(tree.statements.filter(node=>ts.isFunctionDeclaration(node)).map(node=>node.getText(tree)).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
function harness(){
  const requests=[];
  const context=vm.createContext({AbortController,setTimeout,clearTimeout,fetch(url,options){let resolve;const promise=new Promise(yes=>resolve=yes);requests.push({url,options,resolve});return promise;}});
  vm.runInContext(`let tenant='FIRST',csrf='test-csrf',apiPrefix='',enabled=true,data=null,selected='',busy=false,error='',saved=false,step=0,token='',accepted=false,disposed=false,controller;
    ${functions}
    globalThis.subject={run,choose(value){selected=value;},accept(){accepted=true;},dispose(){disposed=true;controller?.abort();},state(){return {data,step,error,saved};}};`,context);
  return {subject:context.subject,requests};
}
function reply(request,data,ok=true){request.resolve({ok,json:async()=>data});}
async function load(subject,requests,can_change_model=true){const work=subject.run('load');reply(requests.at(-1),{tenant:'FIRST',model:'gpt-4o-mini',can_change_model,model_options:[{id:'gpt-4o-mini',input_usd_per_million:.15,output_usd_per_million:.6},{id:'gpt-4o',input_usd_per_million:2.5,output_usd_per_million:10}]});await work;}

test('subscription model save requires both confirmations and sends tenant-scoped CSRF',async()=>{
  const {subject,requests}=harness();await load(subject,requests);subject.choose('gpt-4o');
  const review=subject.run('review');await subject.run('review');assert.equal(requests.length,2);
  assert.equal(requests[1].url,'/admin/api/ai-model/review?tenant=FIRST');
  assert.equal(requests[1].options.headers['X-CSRF-Token'],'test-csrf');
  assert.deepEqual(JSON.parse(requests[1].options.body),{model:'gpt-4o'});
  reply(requests[1],{model:'gpt-4o',token:'review-token'});await review;
  await subject.run('confirm');assert.equal(requests.length,2);
  subject.accept();const confirm=subject.run('confirm');
  assert.deepEqual(JSON.parse(requests[2].options.body),{token:'review-token',acknowledge_cost_and_responses:true});
  reply(requests[2],{model:'gpt-4o',token:'save-token'});await confirm;
  await subject.run('save');assert.equal(requests.length,3);
  subject.accept();const save=subject.run('save');
  assert.equal(requests[3].options.method,'PUT');
  assert.deepEqual(JSON.parse(requests[3].options.body),{token:'save-token',confirm_and_save:true});
  reply(requests[3],{ok:true,model:'gpt-4o'});await save;
  assert.equal(subject.state().data.model,'gpt-4o');assert.equal(subject.state().saved,true);
});
test('leaving a business aborts its model request and discards the late reply',async()=>{
  const {subject,requests}=harness();await load(subject,requests);subject.choose('gpt-4o');const review=subject.run('review');subject.dispose();
  assert.equal(requests[1].options.signal.aborted,true);reply(requests[1],{model:'gpt-4o',token:'late-token'});await review;
  assert.equal(subject.state().step,0);assert.equal(subject.state().data.model,'gpt-4o-mini');
});
test('a read-only model catalog cannot submit a change',async()=>{
  const {subject,requests}=harness();await load(subject,requests,false);subject.choose('gpt-4o');await subject.run('review');assert.equal(requests.length,1);
});
test('wrong-company model data is discarded',async()=>{
  const {subject,requests}=harness();const load=subject.run('load');reply(requests[0],{tenant:'SECOND',model:'gpt-4o',model_options:[]});await load;
  assert.equal(subject.state().data,null);assert.match(subject.state().error,/Refresh and review/);
});
test('an expired or rejected confirmation requires another review',async()=>{
  const {subject,requests}=harness();await load(subject,requests);subject.choose('gpt-4o');const review=subject.run('review');reply(requests[1],{},false);await review;
  assert.equal(subject.state().step,0);assert.equal(subject.state().data.model,'gpt-4o-mini');assert.match(subject.state().error,/Refresh and review/);
});
