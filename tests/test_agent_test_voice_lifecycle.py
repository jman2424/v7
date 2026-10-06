"""Exercise console test voice and request lifecycle without a provider or microphone."""
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
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const ts = require('./frontend/node_modules/typescript/lib/typescript.js');
const scenario = process.argv[1];
let source = fs.readFileSync('frontend/src/lib/AgentTest.svelte','utf8').match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
source = source.replace(/import[^;]+;/g,'').replaceAll('export let','let');
source += `globalThis.h = {send,restart,dictate,listenToReply,stopPlayback,
  draft:(value)=>{draft=value;}, aloud:(value)=>{readAloud=value;},
  state:()=>({draft,messages,token,busy,error,voiceStatus,listening,dictationStarting,speakingMessageId,canDictate,canReadAloud})};
tenant='SHOP';csrf='synthetic-csrf';transcript={scrollTop:0,scrollHeight:0};composer={focus:()=>{}};`;
let mount, destroy, mountCleanup, timerId = 0, cancels = 0;
const timers = new Map(), requests = [], recognitions = [], spoken = [], windowEvents = new Map(), documentEvents = new Map();
class Recognition {
  constructor(){recognitions.push(this);this.starts=0;this.stops=0;this.aborts=0;}
  start(){this.starts++;}
  stop(){this.stops++;}
  abort(){this.aborts++;}
}
class Utterance {constructor(text){this.text=text;}}
const windowMock = {
  isSecureContext:true, SpeechRecognition:Recognition,
  speechSynthesis:{speak:value=>{if(scenario==='audio-failure')throw Error('Audio unavailable');spoken.push(value);},cancel:()=>{cancels++;}},
  setTimeout:(callback,delay)=>{const id=++timerId;timers.set(id,{callback,delay});return id;},
  clearTimeout:id=>timers.delete(id),
  addEventListener:(name,callback)=>windowEvents.set(name,callback),
  removeEventListener:name=>windowEvents.delete(name),
};
const documentMock = {
  documentElement:{lang:'en-GB'},hidden:false,
  addEventListener:(name,callback)=>documentEvents.set(name,callback),
  removeEventListener:name=>documentEvents.delete(name),
};
if(scenario==='unsupported'){delete windowMock.SpeechRecognition;delete windowMock.speechSynthesis;}
const context = vm.createContext({AbortController,Date,
  onMount:callback=>{mount=callback;},onDestroy:callback=>{destroy=callback;},tick:async()=>{},
  window:scenario==='ssr-destroy'?undefined:windowMock,document:documentMock,
  SpeechSynthesisUtterance:scenario==='unsupported'?undefined:Utterance,
  fetch:(path,options)=>new Promise((resolve,reject)=>{
    const request={path,options,resolve:value=>resolve({ok:true,status:200,json:async()=>value}),reject};
    requests.push(request);
    if(scenario==='timeout') options.signal.addEventListener('abort',()=>reject(Error('Private provider detail')),{once:true});
  }),
});
vm.runInContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context);
const h=context.h;
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const response=reply=>({reply,conversation_token:'synthetic-test-conversation',agent:{suggested_replies:[]}});
function runTimer(delay){
  const entry=[...timers].find(([,timer])=>timer.delay===delay);
  assert.ok(entry,'expected timer '+delay);timers.delete(entry[0]);entry[1].callback();
}
(async()=>{
  if(scenario==='ssr-destroy'){destroy();assert.equal(timers.size,0);return;}
  mountCleanup=mount();
  if(scenario==='unsupported'){
    assert.equal(h.state().canDictate,false);assert.equal(h.state().canReadAloud,false);
    h.dictate();h.listenToReply({id:1,from:'Agent',text:'Hello'});
    assert.equal(recognitions.length,0);assert.equal(spoken.length,0);assert.match(h.state().voiceStatus,/unavailable/);
  } else if(scenario==='dictation'){
    assert.equal(recognitions.length,0,'mount must not request microphone access');
    h.dictate();const recognition=recognitions[0];recognition.onstart();
    assert.equal(h.state().listening,true);assert.equal(recognition.starts,1);
    recognition.onresult({results:[[{transcript:'Please tell me about your services'}]]});
    assert.equal(requests.length,0,'dictation must not automatically send');
    assert.match(h.state().draft,/services/);runTimer(30000);assert.equal(recognition.stops,1);
    recognition.onend();assert.equal(h.state().listening,false);
    h.dictate();const late=recognitions[1];late.onstart();const queuedResult=late.onresult;
    const sending=h.send();await flush();assert.equal(late.aborts,1);
    queuedResult({results:[[{transcript:'Late private dictation'}]]});assert.equal(h.state().draft,'');
    requests[0].resolve(response('Here are our services'));await sending;
    assert.equal(h.state().messages.length,2);assert.equal(spoken.length,0,'read aloud must be opt in');
  } else if(scenario==='denied'){
    h.dictate();const recognition=recognitions[0];recognition.onstart();
    recognition.onerror({error:'not-allowed'});recognition.onend();
    assert.equal(h.state().listening,false);assert.match(h.state().voiceStatus,/permission was denied/);
  } else if(scenario==='playback'){
    h.listenToReply({id:1,from:'Agent',text:'First reply'});const first=spoken[0];
    h.listenToReply({id:2,from:'Agent',text:'Second reply'});assert.equal(h.state().speakingMessageId,2);
    first.onend();first.onerror({error:'audio-busy'});assert.equal(h.state().speakingMessageId,2);
    h.listenToReply({id:2,from:'Agent',text:'Second reply'});assert.equal(h.state().speakingMessageId,null);
    h.listenToReply({id:3,from:'Agent',text:'Third reply'});const cancelled=spoken[2];
    h.dictate();assert.equal(h.state().speakingMessageId,null);assert.ok(cancels>=4);
    cancelled.onerror({error:'audio-busy'});assert.equal(h.state().voiceStatus,'Starting microphone…');
    recognitions[0].onstart();documentMock.hidden=true;documentEvents.get('visibilitychange')();
    assert.equal(h.state().listening,false);assert.equal(recognitions[0].aborts,1);
  } else if(scenario==='restart'){
    h.aloud(true);h.draft('Old question');const old=h.send();await flush();
    h.restart();h.draft('New question');const current=h.send();await flush();
    assert.ok(requests[0].options.signal.aborted);
    requests[0].resolve(response('Old reply'));await old;
    assert.equal(h.state().busy,true);assert.equal(h.state().messages.length,1);assert.equal(spoken.length,0);
    requests[1].resolve(response('Current reply'));await current;
    assert.equal(h.state().messages[1].text,'Current reply');assert.equal(spoken.length,1);
    assert.equal(JSON.parse(requests[1].options.body).conversation_token,undefined);
    assert.equal(requests[1].options.headers['X-CSRF-Token'],'synthetic-csrf');
    assert.ok(requests[1].path.endsWith('?tenant=SHOP'));
    h.restart();const speech=spoken[0];speech.onend();speech.onerror({error:'audio-busy'});
    assert.equal(h.state().messages.length,0);assert.equal(h.state().speakingMessageId,null);assert.equal(h.state().voiceStatus,'');
  } else if(scenario==='destroy'){
    h.draft('Question');const sending=h.send();await flush();destroy();
    const before=JSON.stringify(h.state());requests[0].resolve(response('Late reply'));await sending;
    assert.equal(JSON.stringify(h.state()),before);assert.ok(requests[0].options.signal.aborted);
  } else if(scenario==='hidden-reply'){
    h.aloud(true);h.draft('Question');const sending=h.send();await flush();
    documentMock.hidden=true;documentEvents.get('visibilitychange')();
    documentMock.hidden=false;
    requests[0].resolve(response('Reply completed after leaving the page'));await sending;
    assert.equal(h.state().messages.length,2);assert.equal(spoken.length,0,'Leaving the page must cancel pending reply playback too');
  } else if(scenario==='audio-failure'){
    h.aloud(true);h.draft('Question');const sending=h.send();await flush();
    requests[0].resolve(response('A completed text reply'));await sending;
    assert.equal(h.state().messages.length,2);assert.equal(h.state().error,'');assert.equal(h.state().busy,false);
    assert.equal(h.state().draft,'');assert.equal(h.state().speakingMessageId,null);assert.match(h.state().voiceStatus,/Audio could not play/);
  } else if(scenario==='timeout'){
    h.draft('Please help');const sending=h.send();await flush();runTimer(45000);await sending;
    assert.equal(h.state().busy,false);assert.equal(h.state().draft,'Please help');assert.match(h.state().error,/too long/);
    assert.ok(!h.state().error.includes('Private provider'));
    const retry=h.send();await flush();requests[1].resolve(response('A completed reply'));await retry;
    assert.equal(h.state().busy,false);assert.equal(h.state().error,'');assert.equal(h.state().messages.at(-1).text,'A completed reply');
  }
  if(scenario!=='destroy')destroy();
  mountCleanup();assert.equal(timers.size,0);assert.equal(windowEvents.size,0);assert.equal(documentEvents.size,0);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


@pytest.mark.parametrize('scenario', [
    'dictation', 'denied', 'playback', 'restart', 'destroy', 'hidden-reply', 'audio-failure', 'timeout', 'unsupported', 'ssr-destroy',
])
def test_agent_test_voice_and_requests_discard_stale_callbacks(scenario):
    result = subprocess.run([NODE, '-e', SCRIPT, scenario], cwd=ROOT, capture_output=True,
                            text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
