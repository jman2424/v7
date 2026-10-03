"""Signup must finish waiting and retain a recoverable status after a stalled request."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
pytestmark = pytest.mark.skipif(
    not NODE or not (ROOT / 'frontend/node_modules/typescript/lib/typescript.js').exists(),
    reason='Node and frontend npm dependencies are required',
)

SCRIPT = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ts=require('./frontend/node_modules/typescript/lib/typescript.js');
const scenario=process.argv[1];
let source=fs.readFileSync('frontend/src/lib/Registration.svelte','utf8').match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
const ast=ts.createSourceFile('Registration.ts',source,ts.ScriptTarget.Latest,true);
for(const statement of [...ast.statements].reverse()) if(ts.isImportDeclaration(statement)) source=source.slice(0,statement.pos)+source.slice(statement.end);
source=source.replaceAll('export let','let');
source+=`globalThis.h={refresh,submit,state:()=>({loaded,busy,error,state}),
 setup:()=>{email='applicant@synthetic.test';password='Synthetic-test-password-123';tenant='NEWCO';businessName='Test business';},
 verify:()=>{state={status:'verification',email:'applicant@synthetic.test',tenant:'NEWCO'};code='123456';}};`;
const timers=new Map(),calls=[];let id=0,destroy,stalled=true,sessionReads=0,release;
const context=vm.createContext({AbortController,
 onMount:()=>{},onDestroy:callback=>{destroy=callback;},createEventDispatcher:()=>()=>{},
 setTimeout:(callback,delay)=>{const key=++id;timers.set(key,{callback,delay});return key;},clearTimeout:key=>timers.delete(key),
 fetch:async(path,{signal,...options})=>{
   calls.push({path,signal,...options});
   if(path==='/auth/session') {
     sessionReads++;
     return {ok:scenario!=='expired-cookie'||sessionReads>1,status:scenario==='expired-cookie'&&sessionReads===1?401:200,json:async()=>({csrf_token:'fresh'})};
   }
   const target=scenario==='register-timeout'?'/auth/register':scenario==='confirm-timeout'?'/auth/register/confirm':'/auth/registration';
   if(stalled&&path===target&&scenario!=='expired-cookie') {
     return new Promise((resolve,reject)=>{release=resolve;signal.addEventListener('abort',()=>{if(scenario!=='destroy')reject(Error('Private mail provider detail'));},{once:true});});
   }
   return {ok:true,status:200,json:async()=>({enabled:true,request:{status:path==='/auth/register'?'verification':'approved',email:'applicant@synthetic.test',tenant:'NEWCO'}})};
 }
});
vm.runInContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context);
const h=context.h,flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 h.setup();
 if(scenario==='confirm-timeout')h.verify();
 const pending=scenario==='register-timeout'||scenario==='confirm-timeout'||scenario==='expired-cookie'?h.submit():h.refresh();
 await flush();
 if(scenario==='expired-cookie') {
   await pending;assert.equal(sessionReads,2);
   const submission=calls.find(call=>call.path==='/auth/register');
   assert.equal(submission.headers['X-CSRF-Token'],'fresh');assert.equal(submission.credentials,'same-origin');
   assert.equal(h.state().state.status,'verification');
 } else if(scenario==='destroy') {
   const before=JSON.stringify(h.state());destroy();release({ok:true,status:200,json:async()=>({enabled:true,request:null})});await pending;
   assert.equal(JSON.stringify(h.state()),before);assert.ok(calls[0].signal.aborted);
 } else {
   assert.equal(h.state().busy,true);
   for(const [key,timer] of [...timers]) {assert.equal(timer.delay,20000);timers.delete(key);timer.callback();}
   await pending;assert.equal(h.state().busy,false);assert.ok(h.state().error);
   assert.ok(!h.state().error.includes('Private mail provider'));
   assert.equal(calls.filter(call=>call.method==='POST').length,scenario==='status-timeout'?0:1);
   stalled=false;await h.refresh();assert.equal(h.state().loaded,true);assert.equal(h.state().state.status,'approved');
 }
 assert.equal(timers.size,0);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


@pytest.mark.parametrize('scenario', [
    'status-timeout', 'register-timeout', 'confirm-timeout', 'destroy', 'expired-cookie',
])
def test_registration_waiting_and_recovery(scenario):
    result = subprocess.run([NODE, '-e', SCRIPT, scenario], cwd=ROOT, text=True,
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
