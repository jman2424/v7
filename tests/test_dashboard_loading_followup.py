"""Exercise actual dashboard scripts with controllable HTTP and request deadlines."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
TYPESCRIPT = ROOT / 'frontend/node_modules/typescript/lib/typescript.js'
pytestmark = pytest.mark.skipif(
    not NODE or not TYPESCRIPT.exists(), reason='Node and frontend npm dependencies are required',
)

SCRIPT = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('./frontend/node_modules/typescript/lib/typescript.js');
const [screen, scenario] = process.argv.slice(1);
const component = {messages:'Conversations',leads:'Conversations',questions:'Conversations',activity:'ErrorsHealth',health:'ErrorsHealth',statistics:'Statistics'}[screen];
let source = fs.readFileSync(`frontend/src/lib/${component}.svelte`, 'utf8').match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
const ast = ts.createSourceFile(`${component}.ts`, source, ts.ScriptTarget.Latest, true);
const effects = ast.statements.filter(statement => ts.isLabeledStatement(statement) && statement.label.text === '$')
  .map(statement => source.slice(statement.statement.pos, statement.statement.end));
for (const statement of [...ast.statements].reverse()) {
  if (ts.isImportDeclaration(statement) || (ts.isLabeledStatement(statement) && statement.label.text === '$')) {
    source = source.slice(0, statement.pos) + source.slice(statement.end);
  }
}
source = source.replaceAll('export let', 'let');
source += `globalThis.harness = {
  start: (company) => ${component === 'Conversations' ? `refresh(company,'${screen}',1440)` : screen === 'activity' ? 'loadActivity(company,10080)' : screen === 'health' ? 'checkHealth(company)' : "refresh(company,30,'all')"},
  state: () => (${component === 'Conversations' ? '{busy,error,messages,leads,questions,nextBefore}' : screen === 'activity' ? '{busy:loading,error:activityError,data:totals}' : screen === 'health' ? '{busy:checking,error:healthError,data:checks}' : '{busy,error,data}'}),
  tenant: (value) => {tenant=value;},
  effects: () => {${effects.join('\n')}}
};`;
const requests = [];
const timers = new Map();
let timerId = 0, destroy;
const context = vm.createContext({
  AbortController, URLSearchParams, Date, Intl,
  onMount: callback => {}, onDestroy: callback => {destroy=callback;},
  setTimeout: (callback, delay) => {const id=++timerId;timers.set(id,{callback,delay});return id;},
  clearTimeout: id => timers.delete(id),
  fetch: (path, {signal}) => new Promise((resolve,reject) => {
    const request = {path,signal,resolve: value => resolve({ok:true,status:200,json:async()=>value}),reject};
    requests.push(request);
    signal.addEventListener('abort',()=>{
      if (!['stale','destroy'].includes(scenario)) reject(new Error('Private transport failure'));
    },{once:true});
  }),
});
vm.runInContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context);
const h = context.harness;
const flush = () => new Promise(resolve => setImmediate(resolve));
const payload = (request, marker) => {
  if (screen === 'messages') return {messages:[{id:marker,ts_utc:'',channel:'web',event_type:'msg_in',text:String(marker)}],has_more:false};
  if (screen === 'leads') return [{lead_id:String(marker),name:String(marker),updated_utc:''}];
  if (screen === 'questions') return [{question:String(marker),count:marker}];
  if (screen === 'activity') return request.path.includes('/kpis?') ? {errors:marker,fallbacks:0} : [{label:String(marker),count:marker}];
  if (screen === 'health') return {validation:{files:{[String(marker)]:{exists:true,valid:true}}}};
  return {tenant:String(marker),current:{inbound:marker}};
};
function resolveRequests(batch, marker) {for (const request of batch) request.resolve(payload(request,marker));}
function marker(state) {
  if (screen === 'messages') return state.messages[0]?.id;
  if (screen === 'leads') return Number(state.leads[0]?.lead_id);
  if (screen === 'questions') return state.questions[0]?.count;
  if (screen === 'activity') return state.data?.errors;
  if (screen === 'health') return Number(state.data?.[0]?.[0]);
  return state.data?.current?.inbound;
}
(async()=>{
  const first = h.start('OLD');
  const old = [...requests];
  assert.equal(h.state().busy,true);
  assert.equal(timers.size,1);
  assert.equal([...timers.values()][0].delay,20000);
  assert.ok(old.every(request => new URLSearchParams(request.path.split('?')[1]).get('tenant') === 'OLD'));
  if (scenario === 'timeout') {
    for (const [id,timer] of [...timers]) {timers.delete(id);timer.callback();}
    await first;
    assert.equal(h.state().busy,false);
    assert.match(h.state().error,/timed out/);
    assert.ok(old.every(request => request.signal.aborted));
    assert.ok(!h.state().error.includes('Private transport'));
    const next = h.start('NEW');
    assert.equal(h.state().error,'');
    assert.equal(h.state().busy,true);
    resolveRequests(requests.slice(old.length),2);
    await next;
    assert.equal(h.state().busy,false);
    assert.equal(marker(h.state()),2);
  } else if (scenario === 'stale') {
    const next = h.start('NEW');
    assert.ok(old.every(request => request.signal.aborted));
    resolveRequests(requests.slice(old.length),2);
    await next;
    resolveRequests(old,1);
    await first;
    assert.equal(marker(h.state()),2);
    assert.equal(h.state().busy,false);
    assert.equal(h.state().error,'');
  } else if (scenario === 'destroy') {
    const before = JSON.stringify(h.state());
    destroy();
    assert.ok(old.every(request => request.signal.aborted));
    resolveRequests(old,1);
    await first;
    assert.equal(JSON.stringify(h.state()),before);
  } else if (scenario === 'failure') {
    old[0].reject(new Error('Private transport failure'));
    await first;
    assert.equal(h.state().busy,false);
    assert.ok(h.state().error);
    if (screen === 'activity') assert.ok(old.every(request=>request.signal.aborted));
  }
  await flush();
  assert.equal(timers.size,0);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


@pytest.mark.parametrize('screen', ['messages', 'leads', 'questions', 'activity', 'health', 'statistics'])
@pytest.mark.parametrize('scenario', ['timeout', 'stale', 'destroy', 'failure'])
def test_dashboard_requests_finish_or_discard_stale_results(screen: str, scenario: str) -> None:
    result = subprocess.run(
        [NODE, '-e', SCRIPT, screen, scenario], cwd=ROOT, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_statistics_reactive_refresh_tracks_the_selected_tenant() -> None:
    """Ask Svelte's actual compiler to expose which props trigger this reload."""
    script = r"""
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {compile} = require('./frontend/node_modules/svelte/compiler');
const source = fs.readFileSync('frontend/src/lib/Statistics.svelte','utf8');
const output = compile(source,{filename:'Statistics.svelte',generate:'client'}).js.code;
const effects = [...output.matchAll(/legacy_pre_effect\(([\s\S]*?)\n\s*\}\);/g)].map(match=>match[1]);
const refresh = effects.find(effect=>effect.includes('refresh('));
assert.ok(refresh,'The statistics reload must remain reactive');
const dependencies = refresh.split('() => {')[0];
assert.ok(dependencies.includes('tenant()'),'Changing the selected tenant must trigger new statistics');
"""
    result = subprocess.run([NODE, '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
