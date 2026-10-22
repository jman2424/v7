const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');
const ts = require('../node_modules/typescript');
const source = fs.readFileSync(require('node:path').join(__dirname,'../src/lib/Console.svelte'),'utf8').match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
const tree = ts.createSourceFile('Console.ts',source,ts.ScriptTarget.Latest,true);
const names = ['createAccount','updateAccount','restoreOwnerAccount'];
const code = ts.transpileModule(tree.statements.filter(n=>ts.isFunctionDeclaration(n)&&names.includes(n.name?.text)).map(n=>n.getText(tree)).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;

function harness(role,operator=true) {
  const sent=[];
  const scope=vm.createContext({sent});
  vm.runInContext(`
    let tenant='FIRST',csrf='synthetic-csrf',isPlatform=${operator},accountRole=${JSON.stringify(role)};
    let accountEmail='owner@example.test',accountPassword='Synthetic-only-password',accountStatus='',accountError=false;
    let accountViewCosts=false,accountViewSubscriptions=false,selectedViewCosts=true,selectedViewSubscriptions=false;
    let selectedAccountId='owner-id',selectedAccountActive=true,selectedAccountPassword='';
    let accounts=[{id:'owner-id',email:'owner@example.test',roles:[accountRole],permissions:['offerings.read']}];
    async function mutateWorkspace(path,options){sent.push({path,options});return {response:{ok:true},data:{account:{email:accountEmail}},selectedTenant:tenant,activeLoad:{}};}
    function isCurrentWorkspace(){return true;} async function loadAccounts(){}
    ${code}
    this.subject={createAccount,updateAccount,restoreOwnerAccount};
  `,scope);
  return {subject:scope.subject,sent};
}

test('new owner uses role defaults instead of an explicit empty ACL',async()=>{
  const {subject,sent}=harness('business_owner');await subject.createAccount();
  const body=JSON.parse(sent[0].options.body);
  assert.equal(body.roles[0],'business_owner');assert.equal(Object.hasOwn(body,'permissions'),false);
});
test('staff creation retains explicit least-privilege permissions',async()=>{
  const {subject,sent}=harness('business_staff');await subject.createAccount();
  assert.deepEqual(JSON.parse(sent[0].options.body).permissions,[]);
});
test('ordinary owner edits preserve their server-controlled permission subset',async()=>{
  const {subject,sent}=harness('business_owner');await subject.updateAccount();
  assert.deepEqual(JSON.parse(sent[0].options.body),{active:true});
});
test('staff view flags still save explicitly',async()=>{
  const {subject,sent}=harness('business_staff');await subject.updateAccount();
  assert.deepEqual(JSON.parse(sent[0].options.body).permissions,['view_costs']);
});
test('restore is explicit, tenant scoped and never sends a password or platform permissions',async()=>{
  const {subject,sent}=harness('business_owner');await subject.restoreOwnerAccount();
  assert.match(sent[0].path,/tenant=FIRST$/);
  assert.equal(sent[0].options.headers['X-CSRF-Token'],'synthetic-csrf');
  assert.deepEqual(JSON.parse(sent[0].options.body),{restore_owner_access:true});
});
test('non-operator and staff targets cannot invoke the restore control',async()=>{
  for(const [role,operator] of [['business_owner',false],['business_staff',true]]){
    const {subject,sent}=harness(role,operator);await subject.restoreOwnerAccount();assert.equal(sent.length,0);
  }
});
