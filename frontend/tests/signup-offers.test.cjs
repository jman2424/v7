const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const ts = require('../node_modules/typescript');

function harness() {
  const component = fs.readFileSync(path.join(__dirname, '../src/lib/Console.svelte'), 'utf8');
  const source = component.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
  const tree = ts.createSourceFile('Console.ts', source, ts.ScriptTarget.Latest, true);
  const names = ['normalizeOffers', 'changeOfferType', 'validSignupDiscount', 'saveOffers', 'reuseOffer'];
  const selected = tree.statements.filter(node => ts.isFunctionDeclaration(node) && names.includes(node.name?.text));
  assert.equal(selected.length, names.length);
  const functions = ts.transpileModule(selected.map(node => node.getText(tree)).join('\n'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022 }
  }).outputText;
  const requests = [];
  const context = vm.createContext({ crypto: { randomUUID: () => 'test-copy' },
    mutateWorkspace: async (url, options) => {
      requests.push({ url, options });
      return { response: { ok: true }, data: {}, activeLoad: 'current' };
    }, isCurrentWorkspace: () => true });
  vm.runInContext(`
    let tenant='FIRST', csrf='test-csrf', offersStatus='', offersError=false;
    let offers=[{id:'welcome',title:'Welcome saving',description:'Verified new customers only; signup on the business website.',
      deal_type:'custom',discount_type:'percentage',discount_value:10,minimum_spend:0,active:true,archived:false,
      code:'WELCOME10',starts_on:'',ends_on:'2099-12-31',product_skus:['BOTTLE']}];
    const stringList = value => Array.isArray(value) ? value.map(String) : [];
    const slug = value => value.toLowerCase().replace(/ /g,'_');
    ${functions}
    globalThis.subject={
      chooseSignup(){changeOfferType(offers[0],'signup_discount');},
      activate(){offers[0].active=true;},
      reward(value,kind='percentage'){offers[0].discount_value=value;offers[0].discount_type=kind;},
      save:saveOffers,
      reload(){offers=normalizeOffers(JSON.parse(JSON.stringify(offers)));},
      reuse(){reuseOffer(offers[0]);},
      state(){return JSON.parse(JSON.stringify({offers,offersStatus,offersError}));}
    };
  `, context);
  return { subject: context.subject, requests };
}

test('choosing signup stays optional and saving preserves its reward, conditions, code, dates and scope', async () => {
  const { subject, requests } = harness();
  subject.chooseSignup();
  assert.equal(subject.state().offers[0].active, false);
  await subject.save();
  assert.equal(requests.length, 1);
  assert.match(requests[0].url, /tenant=FIRST$/);
  assert.equal(requests[0].options.headers['X-CSRF-Token'], 'test-csrf');
  const saved = JSON.parse(requests[0].options.body)[0];
  assert.equal(saved.active, false);
  assert.equal(saved.discount_value, 10);
  assert.equal(saved.discount_type, 'percentage');
  assert.equal(saved.code, 'WELCOME10');
  assert.equal(saved.ends_on, '2099-12-31');
  assert.deepEqual(saved.product_skus, ['BOTTLE']);
  assert.match(saved.description, /Verified new customers only/);
  assert.equal(Object.hasOwn(saved, 'minimum_spend'), false);
  subject.reload();
  assert.equal(subject.state().offers[0].deal_type, 'signup_discount');
  subject.activate();
  await subject.save();
  assert.equal(JSON.parse(requests[1].options.body)[0].active, true);
});

for (const value of [0, -1, 101, Infinity, NaN, 10.001]) {
  test(`invalid percentage ${value} cannot be submitted`, async () => {
    const { subject, requests } = harness();
    subject.chooseSignup();
    subject.reward(value);
    await subject.save();
    assert.equal(requests.length, 0);
    assert.equal(subject.state().offersError, true);
  });
}

test('a fixed signup saving can exceed 100 GBP and is not treated as a percentage', async () => {
  const { subject, requests } = harness();
  subject.chooseSignup();
  subject.reward(125.5, 'fixed');
  await subject.save();
  const saved = JSON.parse(requests[0].options.body)[0];
  assert.equal(saved.discount_type, 'fixed');
  assert.equal(saved.discount_value, 125.5);
});

test('reusing a signup offer requires explicit activation again', () => {
  const { subject } = harness();
  subject.chooseSignup();
  subject.activate();
  subject.reuse();
  const copy = subject.state().offers[1];
  assert.equal(copy.active, false);
  assert.equal(copy.deal_type, 'signup_discount');
  assert.equal(copy.ends_on, '');
  assert.equal(copy.discount_value, 10);
});

test('signup guidance is translated in every supported locale', () => {
  const dictionary = require('../../dashboard/static/i18n/ui.json');
  const keys = ['Signup discount', 'Signup steps and eligibility',
    'Optional: turn on Offer is active when you are ready to promote this signup discount.',
    'Explain how customers sign up with your business, who qualifies and how they redeem the discount. The assistant explains these terms; it does not create accounts, verify signup or apply checkout discounts.'];
  for (const locale of ['en', 'es', 'fr', 'ar']) {
    for (const key of keys) assert.ok(dictionary[locale][key]?.trim(), `${locale}: ${key}`);
  }
});
