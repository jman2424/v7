const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const {createRequire} = require('node:module');
const fromFrontend = createRequire(path.join(__dirname, '../package.json'));
const ts = fromFrontend('typescript');
const {parse} = fromFrontend('svelte/compiler');
const stores = fromFrontend('svelte/store');
const dictionary = require('../../dashboard/static/i18n/subscription.json');
const component = fs.readFileSync(path.join(__dirname, '../src/lib/Subscription.svelte'), 'utf8');
const creditComponent = fs.readFileSync(path.join(__dirname, '../src/lib/UsageCredits.svelte'), 'utf8');

function loadModule(filename, imports = {}) {
  const source = fs.readFileSync(path.join(__dirname, '../src/lib', filename), 'utf8');
  const output = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true}}).outputText;
  const exports = {};
  vm.runInNewContext(output, {exports, Intl, Date, require(name) {
    if (Object.hasOwn(imports, name)) return imports[name];
    throw new Error('Unexpected test import: ' + name);
  }});
  return exports;
}

const format = loadModule('subscription-format.ts');
const i18n = loadModule('i18n.ts', {
  'svelte/store': stores,
  '../../../dashboard/static/i18n/ui.json': require('../../dashboard/static/i18n/ui.json'),
  '../../../dashboard/static/i18n/features.json': require('../../dashboard/static/i18n/features.json'),
  '../../../dashboard/static/i18n/subscription.json': dictionary,
});

function walk(node, visit, parent) {
  if (!node || typeof node !== 'object') return;
  visit(node, parent);
  for (const value of Object.values(node)) {
    if (Array.isArray(value)) value.forEach(child => walk(child, visit, node));
    else if (value && typeof value === 'object') walk(value, visit, node);
  }
}

function messageKeys(node) {
  if (!node) return [];
  if (node.type === 'Literal' && typeof node.value === 'string') return [node.value];
  if (node.type === 'ConditionalExpression') return [...messageKeys(node.consequent), ...messageKeys(node.alternate)];
  if (node.type === 'LogicalExpression') return [...messageKeys(node.left), ...messageKeys(node.right)];
  if (node.type === 'MemberExpression') return messageKeys(node.object);
  if (node.type === 'ObjectExpression') return node.properties.flatMap(property => messageKeys(property.value));
  return [];
}

test('all subscription labels, conditional statuses and plan service levels have complete translations', () => {
  const keys = new Set(['Small businesses', 'Growing businesses', 'Busy businesses', 'Basic', 'Advanced', 'Standard', 'Assisted', 'Priority']);
  for (const source of [component,creditComponent]) walk(parse(source), (node, parent) => {
    if (node.type === 'CallExpression' && node.callee?.name === '$t') messageKeys(node.arguments[0]).forEach(key => keys.add(key));
    if (node.type === 'Text' && parent?.type !== 'Attribute' && /[A-Za-z]/.test(node.data.trim())) {
      assert.equal(node.data.trim(), 'WhatsApp', 'Untranslated interface text: ' + node.data.trim());
    }
  });
  assert.ok(keys.size > 120, 'Cover the whole subscription interface rather than only plan cards');
  for (const language of ['en', 'es', 'fr', 'ar']) {
    for (const key of keys) assert.ok(dictionary[language][key]?.trim(), language + ' missing ' + key);
  }
});

test('language changes translate a pending success message and interpolate formatted amounts', () => {
  const message = 'Plan selected. Subscribe and pay its one-time setup to activate your business.';
  for (const language of ['en', 'es', 'fr', 'ar']) {
    i18n.language.set(language);
    const translate = stores.get(i18n.t);
    assert.equal(translate(message), dictionary[language][message]);
    const price = format.subscriptionMoney(11880, format.subscriptionLocales[language]);
    const text = translate('{price} / month including {percent}% VAT', {price, percent: '20'});
    assert.ok(text.includes(price));
    assert.doesNotMatch(text, /\{price\}|\{percent\}/);
    assert.equal(translate('{plan} plan', {plan: 'Business'}), dictionary[language]['{plan} plan'].replace('{plan}', 'Business'));
  }
});

test('each translation preserves every dynamic placeholder', () => {
  const placeholders = value => [...value.matchAll(/\{([A-Za-z_]+)\}/g)].map(match => match[1]).sort();
  for (const key of Object.keys(dictionary.en)) {
    for (const language of ['es', 'fr', 'ar']) {
      assert.deepEqual(placeholders(dictionary[language][key]), placeholders(key), language + ': ' + key);
    }
  }
});

test('monthly and setup totals include exclusive VAT and saved discounts in pence', () => {
  for (const [before, total] of [[9900,11880], [19900,23880], [34900,41880], [14900,17880], [29900,35880], [59900,71880]]) {
    const price = format.subscriptionPrice(before, 0, 20);
    assert.equal(price.beforeVat, before);
    assert.equal(price.total, total);
    const discount = format.subscriptionPrice(before, 50, 20);
    assert.equal(discount.beforeVat, before / 2);
    assert.equal(discount.total, total / 2);
  }
  assert.equal(format.subscriptionPrice(99, 50, 20).total, 60, 'Round the discounted line before adding rounded VAT');
  assert.equal(format.subscriptionPrice(9900, 0, 0).total, 9900);
});

test('GBP, counts and calendar months follow the selected locale, including Arabic numerals', () => {
  assert.equal(format.subscriptionMoney(11880, 'en-GB'), '£118.80');
  assert.ok(format.subscriptionMoney(11880, 'es-ES').includes('118,80'));
  assert.ok(format.subscriptionMoney(11880, 'fr-FR').includes('118,80'));
  assert.match(format.subscriptionMoney(11880, format.subscriptionLocales.ar), /[١٢٣٤٥٦٧٨٩٠]/);
  assert.equal(format.subscriptionMonth('2026-10', 'en-GB'), 'October 2026');
  assert.equal(format.subscriptionMonth('2026-10', 'fr-FR'), 'octobre 2026');
  assert.match(format.subscriptionMonth('2026-10', format.subscriptionLocales.ar), /[١٢٣٤٥٦٧٨٩٠]/);
  assert.equal(format.subscriptionMonth('not-a-month', 'en-GB'), 'not-a-month');
});

test('known billing errors are actionable and localized while arbitrary provider/network text is hidden', () => {
  const known = format.subscriptionError('cancel_pending_checkout_before_changing_plan');
  assert.equal(known, 'Cancel the pending checkout before choosing another plan.');
  const fallback = format.subscriptionError('Provider detail: private secret connection url');
  assert.doesNotMatch(fallback, /secret|connection url/);
  assert.equal(format.subscriptionError(known), known, 'Retain a previously normalized safe error');
  for (const language of ['en', 'es', 'fr', 'ar']) {
    i18n.language.set(language);
    const translate = stores.get(i18n.t);
    assert.equal(translate(known), dictionary[language][known]);
    assert.equal(translate(fallback), dictionary[language][fallback]);
  }
});

test('a financial or pricing hold takes priority over a low-credit purchase prompt', () => {
  for (const code of ['financial_review_required','pricing_unavailable']) {
    const alerts = format.subscriptionCreditAlerts([{code:'low_credit'},{code}]);
    assert.deepEqual(Array.from(alerts,row=>row.code),[code]);
  }
  assert.deepEqual(Array.from(format.subscriptionCreditAlerts([{code:'low_credit'}]),row=>row.code),['low_credit']);
});

test('a real billing read/action failure keeps the friendly error through normalization', async () => {
  const script = component.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
  const tree = ts.createSourceFile('Subscription.svelte.ts', script, ts.ScriptTarget.Latest, true);
  const functions = tree.statements.filter(node => ts.isFunctionDeclaration(node) && ['read', 'action', 'refresh', 'listCompanies'].includes(node.name?.text));
  const source = ts.transpileModule(functions.map(node => node.getText(tree)).join('\n'), {compilerOptions: {target: ts.ScriptTarget.ES2022}}).outputText;
  const requests = [];
  const context = vm.createContext({AbortController, setTimeout, clearTimeout,
    subscriptionError: format.subscriptionError,
    fetch: async (url, options) => { requests.push({url, options}); return {ok: false, json: async () => ({error: 'cancel_pending_checkout_before_changing_plan'})}; },
  });
  vm.runInContext(`let tenant='TEST',csrf='test-only-csrf',apiPrefix='',controller,companyController,companyBusy=false,disposed=false,busy=false,error='',message='',data=null,isPlatform=false,discountCode='',page=1,search='';
    ${source}
    globalThis.subject={action,state(){return {error,busy};}};`, context);
  await context.subject.action('select-plan', {plan_id:'business'});
  assert.equal(context.subject.state().error, 'Cancel the pending checkout before choosing another plan.');
  assert.equal(context.subject.state().busy, false);
  assert.match(requests[0].url, /tenant=TEST$/);
  assert.equal(requests[0].options.headers['X-CSRF-Token'], 'test-only-csrf');
  assert.equal(requests[0].options.credentials, 'same-origin');
});

test('plan cards disclose tax totals and separate phone costs without advertising a WhatsApp message quota', () => {
  const plans = component.slice(component.indexOf('<div class="cards plans tiered-plans">'), component.indexOf('{#if planLocked}'));
  assert.match(plans, /totalWithVat\(plan\.monthly_pence\)/);
  assert.match(plans, /totalWithVat\(plan\.setup_pence\)/);
  assert.match(plans, /AI processing paid separately with prepaid usage credit/);
  assert.match(plans, /WhatsApp phone numbers are not included/);
  assert.doesNotMatch(plans, /plan\.whatsapp_messages/);
  const usage = component.slice(component.indexOf('{#if data.allowance}'), component.indexOf('{#if legacyBilling}', component.indexOf('{#if data.allowance}')));
  assert.doesNotMatch(plans, /plan\.ai_budget_pence/);
  assert.match(creditComponent, /\{#if canViewCosts\}/);
  assert.match(creditComponent, /reserved_pence/);
  assert.match(creditComponent, /unknown_reservations/);
  assert.doesNotMatch(usage, /whatsapp_messages\.limit|whatsapp_messages\.paused/);
  assert.match(component, /dir=\{\$language==='ar'\?'rtl':'ltr'\}/);
  assert.match(component, /text-align:start/);
  assert.match(component, /margin-inline-end/);
});

test('WhatsApp uses prepaid credit and historical API charges remain payable without a new approval form',()=>{
  const whatsapp=fs.readFileSync(path.join(__dirname,'../src/lib/WhatsAppConnection.svelte'),'utf8');
  assert.match(whatsapp,/status\.billing\?\.usage_credit/);
  assert.doesNotMatch(whatsapp,/status\.billing\?\.ai_budget|AI processing budget per month/);
  assert.match(component,/action\('checkout',\{kind:'api',month:usageMonth\}\)/);
  assert.doesNotMatch(component,/action\('api-charge'|approves the charge before a separate checkout/);
  const console=fs.readFileSync(path.join(__dirname,'../src/lib/Console.svelte'),'utf8');
  assert.match(console,/subscriptionCreditAlerts\(activation\?\.usage_credit_alerts/);
  assert.match(console,/usageCreditWarning\(alert\.code\)/);
  assert.doesNotMatch(console,/usage_credit_alerts.*available_pence/);
});
