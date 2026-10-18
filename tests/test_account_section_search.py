"""Search matches useful account terms without exposing unauthorized sections."""
import subprocess

from tests.test_console_workspace_loading import NODE, ROOT, SCRIPT, pytestmark


def test_section_search_matches_aliases_and_limits_results():
    script = r"""
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const ts=require('./frontend/node_modules/typescript');
const code=ts.transpileModule(fs.readFileSync('frontend/src/lib/sectionSearch.ts','utf8'),
 {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const context={exports:{}};vm.runInNewContext(code,context);
const find=context.exports.findSections;
const items=[{key:'usage',label:'API usage & cost',description:'AI settings',keywords:'memory models tokens credit',href:'/console/usage?tenant=CLIENT_A',reload:false},
 {key:'subscription',label:'Subscription',description:'Manage payments',keywords:'billing cancel plans',href:'/console/subscription?tenant=CLIENT_A',reload:false}];
assert.equal(find(items,'memory')[0].key,'usage');
assert.equal(find(items,'cancel plan')[0].key,'subscription');
assert.equal(find(items,'memory')[0].href,'/console/usage?tenant=CLIENT_A');
assert.equal(find(items,'not-a-section').length,0);assert.equal(find(items,' ').length,0);
assert.equal(find(Array(20).fill(items[0]),'API').length,8);
assert.equal(find([{...items[0],label:'Configuración',keywords:''}],'configuracion').length,1);
"""
    result = subprocess.run([NODE, '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_section_search_reuses_live_permission_rules():
    script = SCRIPT.replace('globalThis.h={', 'globalThis.h={searchableSections,')
    script += r"""
setImmediate(()=>{
 h.identity({email:'staff@synthetic.test',tenant:'CLIENT_A',roles:['business_staff'],permissions:['conversations.read']});
 assert.deepEqual(Array.from(h.searchableSections()).sort(),['account','conversations']);
 h.identity({email:'owner@synthetic.test',tenant:'CLIENT_B',roles:['business_owner'],permissions:['business_settings.read','view_costs','view_subscriptions']});
 const owner=Array.from(h.searchableSections());
 assert(owner.includes('usage')&&owner.includes('subscription'));
 assert(!owner.includes('platform')&&!owner.includes('errors'));
});
"""
    # Expose the compiled component harness, whose real rules read the current
    # identity. The existing baseline scenario also tests workspace loading.
    script = script.replace('setImmediate(()=>{\n h.identity', 'setImmediate(()=>{\n const h=context.h;\n h.identity')
    result = subprocess.run([NODE, '-e', script, 'pipeline-only'], cwd=ROOT,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
