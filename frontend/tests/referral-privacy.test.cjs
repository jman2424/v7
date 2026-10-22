const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const ts = require('../node_modules/typescript');
const root = path.join(__dirname, '..');
const context = { exports: {}, URLSearchParams };
const source = fs.readFileSync(path.join(root, 'src/lib/referral-link.ts'), 'utf8');
vm.runInNewContext(ts.transpileModule(source, {
  compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}
}).outputText, context);
const codeFromSearch = context.exports.referralCodeFromSearch;

test('a valid referral link prefills the explicit claim without browser storage', () => {
  assert.equal(codeFromSearch('?ref=V7-' + 'ab'.repeat(16)), 'V7-' + 'AB'.repeat(16));
  assert.equal(codeFromSearch('?tenant=EXAMPLE&ref=V7-' + 'C'.repeat(32)), 'V7-' + 'C'.repeat(32));
  assert.equal(codeFromSearch('?tenant=EXAMPLE'), '');
  for (const value of ['INVALID', 'V7-' + 'A'.repeat(31), 'V7-' + 'A'.repeat(33), '<script>', 'V7-' + 'Z'.repeat(32)]) {
    assert.equal(codeFromSearch('?ref=' + encodeURIComponent(value)), '');
  }
});

test('workspace redirect preserves a validated referral URL without any storage API', async () => {
  const component = fs.readFileSync(path.join(root, 'src/lib/Console.svelte'), 'utf8');
  const script = component.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
  const tree = ts.createSourceFile('Console.ts', script, ts.ScriptTarget.Latest, true);
  const fn = tree.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'openDefaultWorkspace');
  const definition = ts.transpileModule(fn.getText(tree), {compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
  const navigations = [];
  const scope = vm.createContext({URLSearchParams, referralCodeFromSearch:codeFromSearch,
    window:{location:{search:'?next=subscription&ref=V7-' + 'a'.repeat(32),pathname:'/console/'}},
    mayOpenScreen:()=>true, defaultWorkspaceScreen:()=> 'subscription', isWidgetSection:()=>false,
    goto:async target=>navigations.push(target)});
  vm.runInContext(`let user={roles:['business_owner']},tenant='EXAMPLE',base='/console',section='pipeline',referralSaved=false; ${definition}; this.run=openDefaultWorkspace;`, scope);
  await scope.run();
  assert.equal(navigations.length, 1);
  assert.match(navigations[0], /ref=V7-a{32}/);
  assert.match(navigations[0], /tenant=EXAMPLE/);
});
