const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const ts = require('../node_modules/typescript');

function functions(filename, names) {
  const component = fs.readFileSync(path.join(__dirname, '../src/lib', filename), 'utf8');
  const source = component.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
  const tree = ts.createSourceFile(filename + '.ts', source, ts.ScriptTarget.Latest, true);
  const selected = tree.statements.filter(node => ts.isFunctionDeclaration(node) && names.includes(node.name?.text));
  assert.equal(selected.length, names.length, 'The tested functions must exist in the component');
  return ts.transpileModule(selected.map(node => node.getText(tree)).join('\n'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022 }
  }).outputText;
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

test('channel review filters search sender, subject and enquiry while retaining the status filter', () => {
  const context = {};
  vm.runInNewContext(functions('BusinessHub.svelte', ['filterOperations'])+';globalThis.filter=filterOperations;', context);
  const rows=[{id:'1',state:'needs_review',source_address:'client@example.com',payload:{subject:'Coating estimate',text:'My Golf'}},
    {id:'2',state:'completed',source_address:'other@example.com',payload:{subject:'Opening hours',text:'Sunday?'}}];
  assert.deepEqual(Array.from(context.filter(rows,' GOLF ','needs_review'),row=>row.id),['1']);
  assert.equal(context.filter(rows,'Coating','completed').length,0);
  assert.deepEqual(Array.from(context.filter(rows,'OTHER@EXAMPLE.COM',''),row=>row.id),['2']);
  assert.equal(context.filter(rows,'','').length,2);
});

test('email preview preserves prices, paragraph breaks and the immutable disclosure without duplication', () => {
  const notice='AI-assisted reply. Please check important details with the business team.';
  const context={emailNotice:notice};
  vm.runInNewContext(functions('BusinessHub.svelte',['emailPreview'])+';globalThis.preview=emailPreview;',context);
  const answer='Small £100\nMedium £150\n\nEstimate only; final quote on inspection.';
  const expected=answer+'\n\n---\n'+notice;
  assert.equal(context.preview(answer),expected);
  assert.equal(context.preview(expected),expected);
  assert.equal(context.preview('<script>example</script>'),'<script>example</script>\n\n---\n'+notice);
});

for (const component of ['BusinessHub.svelte','BusinessEmailSetup.svelte']) {
  test(component+' bounds requests and does not automatically retry an ambiguous write', async () => {
    let abortTimeout,fetches=0,cleared=0;
    const context={AbortController,tenant:'EXAMPLE',csrf:'test-csrf',apiPrefix:'',revision:'v1',address:'support@example.com',provider:'hosted_email',
      controllers:new Set(),errorMessages:{},
      setTimeout(fn,ms){assert.equal(ms,20000);abortTimeout=fn;return 1;},
      clearTimeout(id){assert.equal(id,1);cleared++;},
      fetch:async (_url,options)=>{fetches++;return new Promise((_,reject)=>options.signal.addEventListener('abort',()=>reject(new Error('Abort'))));}};
    const names=component==='BusinessHub.svelte'?['url','call']:['request'];
    vm.runInNewContext(functions(component,names)+`;globalThis.run=()=>${component==='BusinessHub.svelte'?"call('business-channels',{method:'PUT',body:'{}'})":"request('PUT')"};`,context);
    const pending=context.run();
    abortTimeout();
    await assert.rejects(pending,/timed out.*(?:outcome|whether it saved)/);
    assert.equal(fetches,1);
    assert.equal(cleared,1);
    assert.equal(context.controllers.size,0);
    assert.equal(context.address,'support@example.com');
  });
}

function consoleHarness() {
  const pending = deferred();
  const dispatched = [];
  const context = vm.createContext({
    requestJson(path, options) { dispatched.push({ path, options }); return pending.promise; }
  });
  vm.runInContext(`
    function rememberDraft(){}
    let tenant='FIRST', workspaceGeneration=0, user={id:'operator'};
    const pendingWorkspaceMutations=new Map();
    let profile={name:'First business',about:'Original description',email:'',phone:'',website:'',certifications:[],social:{}};
    let profileStatus='',profileError=false,accountStatus='',accountError=false;
    let accountEmail='staff@example.test',accountPassword='Test-only-password',accountRole='business_staff';
    let accountViewCosts=false,accountViewSubscriptions=false,csrf='test-csrf';
    let accountReloads=[];
    async function loadAccounts(...args){accountReloads.push(args);}
    ${functions('Console.svelte', ['workspaceRequest', 'isCurrentWorkspace', 'mutateWorkspace', 'saveProfile', 'createAccount'])}
    globalThis.subject={saveProfile,createAccount,
      switchTenant(){workspaceGeneration++;pendingWorkspaceMutations.clear();tenant='SECOND';profile={name:'Second business',about:'Second description'};profileStatus='';accountEmail='new-staff@example.test';accountStatus='';},
      editProfile(name){profile.name=name;},
      state(){return JSON.parse(JSON.stringify({tenant,profile,profileStatus,profileError,accountEmail,accountStatus,accountReloads}));}
    };
  `, context);
  return { subject: context.subject, pending, dispatched };
}

test('a delayed profile save cannot replace another company after switching', async () => {
  const { subject, pending, dispatched } = consoleHarness();
  const saving = subject.saveProfile();
  assert.match(dispatched[0].path, /tenant=FIRST$/);
  assert.equal(JSON.parse(dispatched[0].options.body).name, 'First business');
  assert.equal(dispatched[0].options.headers['X-CSRF-Token'], 'test-csrf');
  subject.switchTenant();
  pending.resolve({ response: { ok: true }, data: {} });
  await saving;
  assert.equal(subject.state().profile.name, 'Second business');
  assert.equal(subject.state().profileStatus, '');
});

test('a failed write retains the form and reports its uncertain outcome', async () => {
  const { subject, pending } = consoleHarness();
  const saving = subject.saveProfile();
  pending.reject(new Error('Private network exception'));
  await saving;
  assert.equal(subject.state().profile.name, 'First business');
  assert.equal(subject.state().profileError, true);
  assert.match(subject.state().profileStatus, /could not be confirmed/);
  assert.doesNotMatch(subject.state().profileStatus, /Private network exception/);
});

test('a repeated save does not send a duplicate write while the first is pending', async () => {
  const { subject, pending, dispatched } = consoleHarness();
  const saving = subject.saveProfile();
  await subject.saveProfile();
  assert.equal(dispatched.length, 1);
  pending.resolve({ response: { ok: true }, data: {} });
  await saving;
  assert.equal(subject.state().profileStatus, 'Business profile saved.');
});

test('a successful save preserves edits made while its response was pending', async () => {
  const { subject, pending, dispatched } = consoleHarness();
  const saving = subject.saveProfile();
  subject.editProfile('New unsaved business name');
  assert.equal(JSON.parse(dispatched[0].options.body).name, 'First business');
  pending.resolve({ response: { ok: true }, data: {} });
  await saving;
  assert.equal(subject.state().profile.name, 'New unsaved business name');
  assert.match(subject.state().profileStatus, /unsaved edits/);
});

test('a delayed team update cannot clear the next company form or reload its accounts', async () => {
  const { subject, pending, dispatched } = consoleHarness();
  const saving = subject.createAccount();
  assert.match(dispatched[0].path, /tenant=FIRST$/);
  assert.equal(JSON.parse(dispatched[0].options.body).email, 'staff@example.test');
  subject.switchTenant();
  pending.resolve({ response: { ok: true }, data: { account: { email: 'staff@example.test' } } });
  await saving;
  assert.equal(subject.state().accountEmail, 'new-staff@example.test');
  assert.equal(subject.state().accountStatus, '');
  assert.equal(subject.state().accountReloads.length, 0);
});

function subscriptionHarness() {
  const requests = [];
  const redirects = [];
  const context = vm.createContext({ AbortController, setTimeout, clearTimeout,
    subscriptionError() { return 'Billing could not be updated. Refresh payments and try again, or contact your platform administrator.'; },
    window: { location: { assign(url) { redirects.push(url); } } },
    read(path, body, signal) {
      const pending = deferred();
      requests.push({ path, body, signal, pending });
      return pending.promise;
    }
  });
  vm.runInContext(`
    let controller,companyController,companyBusy=false,disposed=false,page=1,search='',companies=[],companyCount=0,hasNext=false,error='';
    let data=null,busy=false,isPlatform=true,message='',discountCode='';
    ${functions('Subscription.svelte', ['listCompanies', 'refresh', 'action'])}
    globalThis.subject={listCompanies,refresh,action,setSearch(value){search=value;},dispose(){disposed=true;controller?.abort();companyController?.abort();},
      state(){return JSON.parse(JSON.stringify({companies,companyCount,hasNext,companyBusy,error,data,busy,message}));}
    };
  `, context);
  return { subject: context.subject, requests, redirects };
}

test('only the latest company search can change the subscription directory', async () => {
  const { subject, requests } = subscriptionHarness();
  subject.setSearch('old');
  const oldSearch = subject.listCompanies();
  subject.setSearch('new');
  const newSearch = subject.listCompanies();
  assert.equal(requests[0].signal.aborted, true);
  requests[1].pending.resolve({ companies: [{ key: 'NEW' }], total: 1, has_next: false });
  await newSearch;
  requests[0].pending.resolve({ companies: [{ key: 'OLD' }], total: 99, has_next: true });
  await oldSearch;
  assert.equal(subject.state().companies[0].key, 'NEW');
  assert.equal(subject.state().companyCount, 1);
  assert.equal(subject.state().hasNext, false);
});

test('a search discarded on navigation does not display a timeout or stale records', async () => {
  const { subject, requests } = subscriptionHarness();
  const search = subject.listCompanies();
  subject.dispose();
  requests[0].pending.reject(new Error('Late failure'));
  await search;
  assert.equal(subject.state().companies.length, 0);
  assert.equal(subject.state().error, '');
});

test('a slow company directory does not delay the selected business billing overview', async () => {
  const { subject, requests } = subscriptionHarness();
  const refresh = subject.refresh();
  requests[0].pending.resolve({ company: 'FIRST', plans: [] });
  await refresh;
  assert.equal(subject.state().data.company, 'FIRST');
  assert.equal(subject.state().busy, false);
  assert.equal(subject.state().companyBusy, true);
  requests[1].pending.resolve({ companies: [], total: 0, has_next: false });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(subject.state().companyBusy, false);
});

test('duplicate billing actions cannot create a second checkout', async () => {
  const { subject, requests, redirects } = subscriptionHarness();
  const checkout = subject.action('checkout', {});
  await subject.action('checkout', {});
  assert.equal(requests.length, 1);
  requests[0].pending.resolve({ url: 'https://checkout.stripe.com/test-only' });
  await checkout;
  assert.deepEqual(redirects, ['https://checkout.stripe.com/test-only']);
});

test('a checkout response discarded on company navigation cannot redirect the new screen', async () => {
  const { subject, requests, redirects } = subscriptionHarness();
  const checkout = subject.action('checkout', {});
  subject.dispose();
  assert.equal(requests[0].signal.aborted, true);
  requests[0].pending.resolve({ url: 'https://checkout.stripe.com/test-only' });
  await checkout;
  assert.deepEqual(redirects, []);
});

test('an older subscription refresh cannot overwrite a newer billing overview', async () => {
  const { subject, requests } = subscriptionHarness();
  const oldRefresh = subject.refresh();
  const currentRefresh = subject.refresh();
  assert.equal(requests[0].signal.aborted, true);
  requests[1].pending.resolve({ company: 'CURRENT' });
  await currentRefresh;
  requests[0].pending.resolve({ company: 'OLD' });
  await oldRefresh;
  assert.equal(subject.state().data.company, 'CURRENT');
  requests[2].pending.resolve({ companies: [], total: 0, has_next: false });
  await new Promise(resolve => setImmediate(resolve));
});


test('removing then adding categories and locations never reuses a surviving reference', () => {
  const scope = {crypto:require('node:crypto').webcrypto};
  vm.runInNewContext(`
    let catalog={categories:[{id:'category_1'},{id:'category_2'},{id:'category_3'}]};
    let branches=[{id:'branch_1'},{id:'branch_2'},{id:'branch_3'}];
    const emptyHours=()=>({});
    ${functions('Console.svelte',['addCategory','removeCategory','addBranch','removeBranch'])}
    removeCategory(0);addCategory();removeBranch(0);addBranch();
    globalThis.categoryIds=catalog.categories.map(row=>row.id);
    globalThis.branchIds=branches.map(row=>row.id);
  `, scope);
  assert.equal(new Set(scope.categoryIds).size,3);
  assert.equal(new Set(scope.branchIds).size,3);
  assert.deepEqual(Array.from(scope.categoryIds.slice(0,2)),['category_2','category_3']);
  assert.deepEqual(Array.from(scope.branchIds.slice(0,2)),['branch_2','branch_3']);
});
