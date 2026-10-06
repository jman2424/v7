"""Exercise customer-widget privacy and playback using mocked browser services."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="Node is required for widget runtime checks")

SCRIPT = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const scenario = process.argv[1];
class Element {
  constructor() {
    this.children=[];this.listeners={};this.attributes={};this.value='';this.checked=false;
    this.hidden=false;this.disabled=false;this.textContent='';this.style={values:{},setProperty(k,v){this.values[k]=v;}};
    this.classList={toggle(){},contains(){return false;}};this.parentElement={title:''};
  }
  addEventListener(name, callback){(this.listeners[name] ||= []).push(callback);}
  async fire(name){for(const callback of this.listeners[name] || []) await callback({preventDefault(){}});}
  setAttribute(name,value){this.attributes[name]=value;}
  getAttribute(name){return this.attributes[name];}
  append(child){this.children.push(child);}
  replaceChildren(){this.children=[];}
  get childElementCount(){return this.children.length;}
  focus(){} reset(){} reportValidity(){return true;}
}
const elements={};
const get=id=>elements[id] ||= new Element();
get('dictate').hidden=true;get('dictate').setAttribute('aria-pressed','false');
const body=new Element();body.dataset={style:'studio'};
const document={body,documentElement:{lang:'en'},referrer:'https://business.example/page',hidden:false,
  getElementById:get,createElement:()=>new Element(),listeners:{},
  addEventListener(name,callback){this.listeners[name]=callback;}};
let starts=0, stops=0, cancels=0, recognition, recording, trackStops=0, utterances=[];
const mediaPending=[], mediaStops=[], recorderStops=[];
function mediaStream() {
  const index=mediaStops.length;mediaStops.push(0);let stopped=false;
  return {getTracks:()=>[{stop(){if(!stopped){trackStops++;mediaStops[index]++;stopped=true;}}}]};
}
class Recognition {
  constructor(){recognition=this;}
  start(){starts++;this.onstart();}
  stop(){stops++;this.onend();}
  abort(){stops++;this.onend();}
}
class Recorder {
  static isTypeSupported(){return true;}
  constructor(){this.mimeType='audio/webm';this.state='inactive';recording=this;}
  start(){this.state='recording';}
  stop(){this.state='inactive';this.ondataavailable({data:new Blob(['audio'],{type:'audio/webm'})});
    if(scenario==='server-stop-race') recorderStops.push(()=>this.onstop());else this.onstop();}
}
const timers=new Map();let timerId=0;
const pending=[];
const requests=[];
const config={tenant:'EXAMPLE',endpoint:'/chat_api',actionsEndpoint:'/chat/actions',theme:{},accentColor:'#ffffff',
  colors:{background:'#fafafa',surface:'#101010',text:'#eeeeee',bubble:'#ffffff'},
  parentOrigins:['https://business.example'],
  transcriptionEnabled:scenario.startsWith('server-'),transcriptionEndpoint:'/chat/transcribe',transcriptionToken:'synthetic-only'};
const window={__WIDGET__:config,isSecureContext:true,
  speechSynthesis:{cancel(){cancels++;},speak(utterance){utterances.push(utterance);}},
  SpeechSynthesisUtterance:class {constructor(text){this.text=text;}},
  parent:{postMessage(data,origin){assert.equal(data.type,'V7_WIDGET_CLOSE');assert.equal(origin,'https://business.example');}},
  listeners:{},addEventListener(name,callback){this.listeners[name]=callback;}};
if(scenario !== 'unsupported' && !scenario.startsWith('server-')) window.SpeechRecognition=Recognition;
if(scenario.startsWith('server-')) window.MediaRecorder=Recorder;
if(scenario==='unsupported'){delete window.speechSynthesis;delete window.SpeechSynthesisUtterance;}
const context=vm.createContext({window,document,console,Blob,FormData,URL,AbortController,Uint8Array,
  navigator:{mediaDevices:{getUserMedia:async()=>scenario==='server-permission-race'
    ? new Promise(resolve=>mediaPending.push(resolve)) : mediaStream()}},
  MediaRecorder:Recorder,sessionStorage:{getItem(){return '';},setItem(){}},
  setTimeout(callback,delay){const id=++timerId;timers.set(id,{callback,delay});return id;},clearTimeout:id=>timers.delete(id),
  fetch:async(url,options={})=>{
    requests.push({url:String(url),options});
    if(String(url).includes('/chat/actions')) return {ok:true,json:async()=>({conversation_token:'synthetic-only'})};
    if(String(url).includes('/chat/transcribe')) return new Promise(resolve=>pending.push(resolve));
    if(scenario.startsWith('late-playback')) return new Promise(resolve=>pending.push(resolve));
    return {ok:true,json:async()=>({reply:'Our opening hours are 9am to 5pm.',conversation_token:'synthetic-only'})};
  }});
// The browser resolves relative action URLs against the current widget origin.
window.location={origin:'https://widget.example'};
vm.runInContext(fs.readFileSync('dashboard/static/js/widget.js','utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const rgb=hex=>[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255);
const lum=hex=>rgb(hex).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
const contrast=(a,b)=>(Math.max(lum(a),lum(b))+.05)/(Math.min(lum(a),lum(b))+.05);
(async()=>{
  await flush();
  assert.equal(starts,0,'Microphone must not start on page load');
  assert.equal(utterances.length,0,'Audio must not start on page load');
  if(scenario==='palette') {
    const s=body.style.values;
    for(const [surface,text] of [['--wbg','--wtext'],['--wpanel','--wpanel-text'],['--wfield','--wfield-text'],['--wme','--wme-text'],['--waccent','--waccent-text']]) {
      assert.ok(contrast(s[surface],s[text])>=4.5,`${surface} needs readable text`);
    }
    assert.equal(s['--wbg'],'#fafafa');assert.equal(s['--wpanel'],'#101010');
    assert.equal(s['--wpanel-text'],'#eeeeee','Readable custom text is retained');
    assert.equal(s['--wtext'],'#000000','Unreadable custom text receives a readable fallback');
  } else if(scenario==='microphone') {
    await get('dictate').fire('click');assert.equal(starts,1);assert.equal(get('dictate').getAttribute('aria-pressed'),'true');
    assert.ok([...timers.values()].some(timer=>timer.delay===30000));
    recognition.onresult({results:[[{transcript:'Could I visit today?'}]]});
    assert.equal(get('chat-input').value,'Could I visit today?');
    await get('chat-form').fire('submit');
    recognition.onresult({results:[[{transcript:'Late private speech'}]]});
    assert.equal(get('chat-input').value,'','Late results must not repopulate the next draft');
    assert.equal(utterances.length,0,'Reply playback stays opt-in');
    assert.equal(requests.filter(item=>item.url==='/chat_api').length,1,'Dictation never sends a message itself');
    await get('dictate').fire('click');recognition.onerror({error:'not-allowed'});recognition.onend();
    assert.match(get('voice-status').textContent,/permission denied/);assert.equal(get('dictate').disabled,false);
  } else if(scenario==='playback') {
    get('chat-input').value='Opening hours';await get('chat-form').fire('submit');
    const button=get('chat-log').children.at(-1).children[0].children.at(-1);
    assert.equal(button.textContent,'Listen');assert.equal(utterances.length,0);
    await button.fire('click');assert.equal(utterances.length,1);assert.equal(button.getAttribute('aria-pressed'),'true');
    await button.fire('click');assert.equal(button.textContent,'Listen');assert.equal(button.getAttribute('aria-pressed'),'false');
    const cancelled=cancels;get('read-aloud').checked=true;get('chat-input').value='Thanks';await get('chat-form').fire('submit');
    assert.equal(utterances.length,2);await get('dictate').fire('click');assert.ok(cancels>cancelled);
    window.listeners.pagehide();assert.equal(get('stop-speaking').hidden,true);
  } else if(scenario==='server-cancel') {
    await get('dictate').fire('click');assert.equal(recording.state,'recording');
    await get('dictate').fire('click');await flush();assert.equal(pending.length,1);assert.equal(trackStops,1);
    get('chat-input').value='Typed instead';await get('chat-form').fire('submit');
    const upload=requests.find(item=>item.url==='/chat/transcribe');assert.equal(upload.options.signal.aborted,true);
    pending[0]({ok:true,json:async()=>({text:'Late recording transcript'})});await flush();
    assert.equal(get('chat-input').value,'','Discarded uploads must not repopulate a later draft');
    assert.equal(get('dictate').disabled,false,'Cancelling an upload must leave the microphone reusable');
  } else if(scenario==='server-permission-race') {
    const older=get('dictate').fire('click');await flush();assert.equal(mediaPending.length,1);
    get('chat-input').value='Typed instead';await get('chat-form').fire('submit');
    const current=get('dictate').fire('click');await flush();assert.equal(mediaPending.length,2);
    mediaPending[1](mediaStream());await current;assert.equal(recording.state,'recording');
    mediaPending[0](mediaStream());await older;
    assert.deepEqual(mediaStops,[0,1],'A stale permission result must stop only its own tracks');
    assert.equal(get('dictate').getAttribute('aria-pressed'),'true');assert.equal(get('dictate').disabled,false);
    window.listeners.pagehide();assert.deepEqual(mediaStops,[1,1],'The active stream remains owned and can be released');
  } else if(scenario==='server-stop-race') {
    await get('dictate').fire('click');get('chat-input').value='Typed instead';await get('chat-form').fire('submit');
    assert.deepEqual(mediaStops,[1],'Sending typed text immediately stops microphone tracks');
    await get('dictate').fire('click');assert.deepEqual(mediaStops,[1,0]);
    await recorderStops[0]();
    assert.deepEqual(mediaStops,[1,0],'An old recorder stop must not release the newer stream');
    assert.equal(get('dictate').getAttribute('aria-pressed'),'true');assert.equal(get('dictate').disabled,false);
    window.listeners.pagehide();assert.deepEqual(mediaStops,[1,1]);
  } else if(scenario==='launcher-close-native') {
    get('read-aloud').checked=true;get('chat-input').value='Please reply';await get('chat-form').fire('submit');
    assert.equal(utterances.length,1);const before=cancels;
    window.listeners.message({source:window.parent,origin:'https://business.example',data:{type:'V7_WIDGET_HIDE'}});
    assert.ok(cancels>before);assert.equal(get('stop-speaking').hidden,true);
    await get('dictate').fire('click');assert.equal(get('dictate').getAttribute('aria-pressed'),'true');
    window.listeners.message({source:{},origin:'https://business.example',data:{type:'V7_WIDGET_HIDE'}});
    window.listeners.message({source:window.parent,origin:'https://unapproved.example',data:{type:'V7_WIDGET_HIDE'}});
    assert.equal(get('dictate').getAttribute('aria-pressed'),'true','Foreign messages must not control the microphone');
    window.listeners.message({source:window.parent,origin:'https://business.example',data:{type:'V7_WIDGET_HIDE'}});
    assert.equal(get('dictate').getAttribute('aria-pressed'),'false');
    recognition.onresult({results:[[{transcript:'Late speech after launcher close'}]]});
    assert.equal(get('chat-input').value,'');
  } else if(scenario==='server-launcher-close') {
    const hide=()=>window.listeners.message({source:window.parent,origin:'https://business.example',data:{type:'V7_WIDGET_HIDE'}});
    await get('dictate').fire('click');hide();
    assert.equal(trackStops,1);assert.equal(get('dictate').getAttribute('aria-pressed'),'false');
    assert.equal(pending.length,0,'Hiding while recording discards audio without uploading it');
    await get('dictate').fire('click');await get('dictate').fire('click');await flush();
    assert.equal(pending.length,1);hide();
    assert.equal(requests.find(item=>item.url==='/chat/transcribe').options.signal.aborted,true);
    pending[0]({ok:true,json:async()=>({text:'Late transcript after launcher close'})});await flush();
    assert.equal(get('chat-input').value,'');assert.equal(get('dictate').disabled,false);
  } else if(scenario.startsWith('late-playback')) {
    get('read-aloud').checked=true;get('chat-input').value='Please reply';
    const response=get('chat-form').fire('submit');await flush();assert.equal(pending.length,1);
    if(scenario.endsWith('hidden')) {document.hidden=true;document.listeners.visibilitychange();}
    else if(scenario.endsWith('closed')) await get('chat-close').fire('click');
    else if(scenario.endsWith('launcher')) window.listeners.message({source:window.parent,origin:'https://business.example',data:{type:'V7_WIDGET_HIDE'}});
    else window.listeners.pagehide();
    pending[0]({ok:true,json:async()=>({reply:'A late reply',conversation_token:'synthetic-only'})});await response;
    assert.equal(utterances.length,0,'Late replies must not restart audio after voice cleanup');
  } else if(scenario==='unsupported') {
    assert.equal(get('dictate').hidden,true);assert.equal(get('read-aloud').disabled,true);
    assert.match(get('voice-status').textContent,/type your message/);
    get('chat-input').value='Typed chat works';await get('chat-form').fire('submit');
    assert.equal(get('chat-send').disabled,false);assert.equal(get('chat-log').children.length,2);
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


@pytest.mark.parametrize("scenario", [
    "palette", "microphone", "playback", "server-cancel", "unsupported",
    "late-playback-hidden", "late-playback-closed", "late-playback-pagehide",
    "server-permission-race", "server-stop-race",
    "launcher-close-native", "server-launcher-close", "late-playback-launcher",
])
def test_customer_widget_runtime(scenario):
    result = subprocess.run(
        [NODE, "-e", SCRIPT, scenario], cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_embed_launcher_notifies_its_widget_before_hiding():
    from routes.webchat_routes import _embed_javascript

    launcher_script = _embed_javascript("EXAMPLE", {"widget": {"allowed_origins": ["https://business.example"]}})
    harness = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let root,launcher,frame;const notifications=[];
class Element {
  constructor(type){this.type=type;this.listeners={};this.attributes={};this.children=[];
    this.style={set cssText(value){this.display=value.match(/display:([^;]+)/)?.[1];}};
    if(type==='iframe') this.contentWindow={postMessage(data,origin){
      assert.equal(data.type,'V7_WIDGET_HIDE');assert.equal(origin,'https://widget.example');
      assert.equal(frame.style.display,'block','Notify the child before hiding its frame');notifications.push(data);
    }};
  }
  setAttribute(name,value){this.attributes[name]=value;}
  appendChild(child){this.children.push(child);}
  addEventListener(name,callback){this.listeners[name]=callback;}
  focus(){}
}
const window={location:{href:'https://business.example/'},listeners:{},addEventListener(name,callback){this.listeners[name]=callback;}};
const document={currentScript:{src:'https://widget.example/widget.js?tenant=EXAMPLE',dataset:{}},
  getElementById(){return null;},body:new Element('body'),createElement(type){
    const element=new Element(type);if(type==='div'&&!root)root=element;if(type==='button')launcher=element;if(type==='iframe')frame=element;return element;
  }};
vm.runInNewContext(fs.readFileSync(0,'utf8'),{document,window,URL,console});
launcher.listeners.click();assert.equal(frame.style.display,'block');
launcher.listeners.click();assert.equal(frame.style.display,'none');assert.equal(notifications.length,1);
launcher.listeners.click();root.listeners.keydown({key:'Escape'});assert.equal(frame.style.display,'none');assert.equal(notifications.length,2);
launcher.listeners.click();window.listeners.message({origin:'https://unapproved.example',source:frame.contentWindow,data:{type:'V7_WIDGET_CLOSE'}});
assert.equal(frame.style.display,'block');assert.equal(notifications.length,2);
window.listeners.message({origin:'https://widget.example',source:frame.contentWindow,data:{type:'V7_WIDGET_CLOSE'}});
assert.equal(frame.style.display,'none');assert.equal(notifications.length,3);
"""
    result = subprocess.run(
        [NODE, "-e", harness], cwd=ROOT, input=launcher_script,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
