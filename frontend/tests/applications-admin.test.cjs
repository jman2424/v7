const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ts=require('../node_modules/typescript');
const test=require('node:test');
const read=name=>fs.readFileSync(path.join(__dirname,'../src/lib/'+name),'utf8');
const scope={exports:{}};
vm.runInNewContext(ts.transpileModule(read('applicationsText.ts'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,scope);
const text=scope.exports;

test('the administrator is told plainly how many applications are waiting',()=>{
  assert.equal(text.waitingText(1),'1 business application is waiting for your decision.');
  assert.equal(text.waitingText(4),'4 business applications are waiting for your decision.');
  assert.equal(text.statusText('PENDING_REVIEW'),'Waiting for your decision');
  assert.equal(text.statusText('NEEDS_INFORMATION'),'Waiting for the applicant');
});
test('asking for more information needs a question; other decisions do not',()=>{
  assert.match(text.decisionProblem('request_information','  '),/Write what you need/);
  assert.equal(text.decisionProblem('request_information','Which products do you sell?'),'');
  for(const decision of ['approve','reject','note','expire'])assert.equal(text.decisionProblem(decision,''),'');
  assert.match(text.decisionNotice('approve','Corner Shop'),/Corner Shop is approved/);
  assert.match(text.decisionNotice('note','Corner Shop'),/applicant was not contacted/);
});
test('the alert is shown only to the platform administrator and only reads the queue',()=>{
  const consoleSource=read('Console.svelte'),alert=read('ApplicationsAlert.svelte'),screen=read('BusinessApplications.svelte');
  assert.match(consoleSource,/\{#if isPlatform && section !== 'applications'\}<ApplicationsAlert /);
  assert.match(consoleSource,/section === 'applications' && isPlatform/);
  assert.match(alert,/\/business-applications\/queue\?page=1/);
  assert.doesNotMatch(alert,/method:|POST|PUT/);
  // Decisions stay explicit human actions with the CSRF token and the reviewed revision.
  assert.match(screen,/'X-CSRF-Token':csrf/);
  assert.match(screen,/\{revision:selected\.revision,decision,note,message\}/);
  for(const label of ['Approve {selected.business_name}','Ask for more information','Do not approve'])assert.ok(screen.includes(label));
});
