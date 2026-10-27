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
  async fire(name,event={preventDefault(){}}){for(const callback of this.listeners[name] || []) await callback(event);}
  setAttribute(name,value){this.attributes[name]=value;}
  getAttribute(name){return this.attributes[name];}
  append(child){this.children.push(child);}
  replaceChildren(){this.children=[];}
  get childElementCount(){return this.children.length;}
  focus(){document.activeElement=this;this.focusCalls=(this.focusCalls || 0)+1;}
  click(){return this.fire('click');} reset(){} reportValidity(){return true;}
}
const elements={};
const get=id=>elements[id] ||= new Element();
get('dictate').hidden=true;get('dictate').setAttribute('aria-pressed','false');
const body=new Element();body.dataset={style:'studio'};
const document={body,documentElement:{lang:'en'},referrer:'https://business.example/page',hidden:false,
  activeElement:body,
  getElementById:get,createElement:()=>new Element(),listeners:{},
  addEventListener(name,callback){this.listeners[name]=callback;}};
let starts=0, stops=0, cancels=0, recognition, recording, trackStops=0, audioCloses=0, utterances=[];
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
class AudioContext {
  constructor(options){assert.equal(options.sampleRate,16000);}
  decodeAudioData(){
    if(['server-audio-decode-timeout','server-audio-decode-cancel'].includes(scenario)) return new Promise(()=>{});
    const length=scenario==='server-audio-too-long'?16000*61:4;
    const left=Float32Array.from(scenario==='server-audio-invalid'?[NaN,0,0,0]:[-2,-0.5,0.5,2]);
    const right=Float32Array.from([0,0.5,-0.5,0]);
    return Promise.resolve({sampleRate:16000,length,numberOfChannels:2,getChannelData:index=>index?right:left});
  }
  close(){audioCloses++;return Promise.resolve();}
}
const timers=new Map();let timerId=0;
const pending=[];
const requests=[];
let storedToken=scenario==='chat-expired'?'stale-conversation':scenario==='restore-chat'?'synthetic-only':'';
const browserState=new Map();
if(scenario==='restore-chat')browserState.set('transcript:EXAMPLE',JSON.stringify({version:1,token:storedToken,expires:Date.now()+3600000,
  messages:[{from:'me',text:'My car is a Polo'},{from:'bot',text:'Small car. This is an estimate.',actions:[{type:'navigate',label:'Services',url:'https://shop.example/services',click_token:'signed',clicked:true}]}],draft:'What about polishing?',pending:''}));
let closeNotifications=0,readyNotifications=0;
const config={tenant:'EXAMPLE',endpoint:'/chat_api',actionsEndpoint:'/chat/actions',navigationClickEndpoint:'/chat/navigation-click',theme:{},accentColor:'#ffffff',
  deferActions:['preloaded-actions','restore-chat'].includes(scenario),
  colors:{background:'#fafafa',surface:'#101010',text:'#eeeeee',bubble:'#ffffff'},
  parentOrigins:['https://business.example'],
  transcriptionEnabled:scenario.startsWith('server-'),transcriptionEndpoint:'/chat/transcribe',transcriptionToken:'synthetic-only'};
const window={__WIDGET__:config,isSecureContext:true,
  // Hidden iframes can suspend animation callbacks until made visible.
  requestAnimationFrame(){return 1;},
  speechSynthesis:{cancel(){cancels++;},speak(utterance){utterances.push(utterance);}},
  SpeechSynthesisUtterance:class {constructor(text){this.text=text;}},
  parent:{postMessage(data,origin){assert.equal(origin,'https://business.example');
    if(data.type==='V7_WIDGET_READY'){assert.equal(data.loadId,'1');readyNotifications++;return;}
    assert.equal(data.type,'V7_WIDGET_CLOSE');closeNotifications++;}},
  listeners:{},addEventListener(name,callback){this.listeners[name]=callback;}};
let tabChannel;
if(scenario.startsWith('cross-tab'))window.BroadcastChannel=class {
  constructor(name){assert.equal(name,'v7-chat:EXAMPLE:https://business.example');tabChannel=this;}
  postMessage(data){assert.ok(['state','request'].includes(data.type));}
};
if(scenario !== 'unsupported' && !scenario.startsWith('server-')) window.SpeechRecognition=Recognition;
if(scenario.startsWith('server-')) {window.MediaRecorder=Recorder;window.AudioContext=AudioContext;}
if(scenario==='unsupported'){delete window.speechSynthesis;delete window.SpeechSynthesisUtterance;}
const context=vm.createContext({window,document,console,Blob,FormData,URL,AbortController,Uint8Array,
  navigator:{mediaDevices:{getUserMedia:async()=>scenario==='server-permission-race'
    ? new Promise(resolve=>mediaPending.push(resolve)) : mediaStream()}},
  MediaRecorder:Recorder,sessionStorage:{getItem(key){if(scenario==='cross-tab-blocked')throw Error('blocked');return key==='conversation:EXAMPLE'?storedToken:browserState.get(key)||null;},setItem(key,value){if(scenario==='cross-tab-blocked')throw Error('full');if(key==='conversation:EXAMPLE')storedToken=value;else browserState.set(key,value);},removeItem:key=>browserState.delete(key)},
  setTimeout(callback,delay){const id=++timerId;timers.set(id,{callback,delay});return id;},clearTimeout:id=>timers.delete(id),
  fetch:async(url,options={})=>{
    requests.push({url:String(url),options});
    if(String(url).includes('/chat/actions')) {
      if(scenario==='actions-unavailable-chat') throw Error('PRIVATE_ACTION_FAILURE');
      return {ok:true,json:async()=>({conversation_token:'synthetic-only'})};
    }
    if(String(url).includes('/chat/navigation-click')) {
      if(scenario==='navigation-failure') throw new Error('Telemetry unavailable');
      return {ok:true,json:async()=>({ok:true})};
    }
    if(scenario.startsWith('navigation-')) return {ok:true,json:async()=>({
      reply:'Open our product page.',conversation_token:requests.filter(item=>item.url==='/chat_api').length>1?'second-conversation':'synthetic-only',
      actions:[{type:'navigate',label:'See products',url:'https://shop.example/products#catalog',click_token:'issued-button-proof'}]
    })};
    if(String(url).includes('/chat/transcribe')) return new Promise(resolve=>pending.push(resolve));
    if(scenario.startsWith('late-playback')) return new Promise(resolve=>pending.push(resolve));
    if(scenario.startsWith('pending-chat')) return new Promise(resolve=>pending.push(resolve));
    if(scenario==='cross-tab-concurrent') return new Promise(resolve=>pending.push(resolve));
    if(scenario==='chat-paused') return {ok:false,status:429,json:async()=>({error:'website_allowance_paused'})};
    if(scenario==='chat-rate-limit') return {ok:false,status:429,json:async()=>({error:'rate_limited'})};
    if(scenario==='chat-expired') return {ok:false,status:403,json:async()=>({error:'conversation_expired'})};
    if(scenario==='chat-cold-start') return {ok:false,status:503,headers:{get:name=>name==='Content-Type'?'text/html':null},json:async()=>{throw Error('Render loading page');}};
    if(scenario==='chat-provider-reference') return {ok:false,status:503,headers:{get:name=>name==='X-Request-ID'?'a'.repeat(24):'application/json'},json:async()=>({error:'agent_failure'})};
    if(scenario==='chat-first-timeout') throw Object.assign(Error('PRIVATE_TIMEOUT_BODY'),{name:'AbortError'});
    if(scenario==='chat-malformed') return {ok:true,json:async()=>({reply:null})};
    return {ok:true,json:async()=>({reply:'Our opening hours are 9am to 5pm.',conversation_token:'synthetic-only'})};
  }});
// The browser resolves relative action URLs against the current widget origin.
window.location={origin:'https://widget.example',href:'https://widget.example/chat_ui?v7_load=1'};
vm.runInContext(fs.readFileSync('dashboard/static/js/widget-session.js','utf8'),context);
vm.runInContext(fs.readFileSync('dashboard/static/js/widget.js','utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const rgb=hex=>[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255);
const lum=hex=>rgb(hex).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
const contrast=(a,b)=>(Math.max(lum(a),lum(b))+.05)/(Math.min(lum(a),lum(b))+.05);
(async()=>{
  await flush();
  assert.equal(readyNotifications,1,'The styled widget announces readiness once without customer data');
  assert.equal(starts,0,'Microphone must not start on page load');
  assert.equal(utterances.length,0,'Audio must not start on page load');
  if(scenario.startsWith('cross-tab')) {
    const before=requests.length;
    get('chat-input').value='Keep my private draft';
    const value=JSON.stringify({version:1,token:'shared-conversation',expires:Date.now()+3600000,
      messages:[{from:'me',text:'My car is a Polo'},{from:'bot',text:'Small car. This is an estimate.',actions:[]}],draft:'',pending:''});
    tabChannel.onmessage({data:{type:'state',value}});
    assert.equal(get('chat-log').children.length,2);assert.equal(get('chat-input').value,'Keep my private draft');
    assert.equal(requests.length,before,'Receiving another tab never resends a message');
    const sending=get('chat-form').fire('submit');
    if(scenario==='cross-tab-concurrent') {
      const remote=JSON.parse(value);remote.messages.push({id:'other-reply',at:Date.now()+1,from:'bot',text:'Another completed exchange',actions:[]});
      tabChannel.onmessage({data:{type:'state',value:JSON.stringify(remote)}});
      pending.shift()({ok:true,json:async()=>({reply:'My completed exchange',conversation_token:'shared-conversation'})});
    }
    await sending;
    const followup=requests.find(item=>item.url==='/chat_api');
    assert.equal(JSON.parse(followup.options.body).conversation_token,'shared-conversation');
    assert.equal(utterances.length,0,'Cross-tab restoration never plays audio');
    if(scenario==='cross-tab-concurrent') {
      const texts=()=>get('chat-log').children.map(row=>row.children[0].children[0].textContent);
      assert.ok(texts().includes('My completed exchange'));assert.ok(texts().includes('Another completed exchange'));
      tabChannel.onmessage({data:{type:'state',value}});
      assert.ok(texts().includes('My completed exchange'),'An older snapshot cannot remove a completed reply');
      assert.ok(texts().includes('Another completed exchange'));
    }
  } else if(scenario==='restore-chat') {
    assert.equal(requests.length,0,'Restoration does not send another request');
    assert.equal(get('chat-log').children.length,2);assert.equal(get('chat-input').value,'What about polishing?');
    const bubble=get('chat-log').children[1].children[0];
    assert.equal(bubble.children[0].textContent,'Small car. This is an estimate.');
    assert.equal(bubble.children[1].children[0].textContent,'Services · Clicked');
    await get('chat-form').fire('submit');
    assert.equal(JSON.parse(requests[0].options.body).conversation_token,'synthetic-only','Follow-up keeps the server conversation');
    assert.equal(get('chat-log').children.length,4);
    const current=JSON.parse(browserState.get('transcript:EXAMPLE'));
    current.messages.push({from:'bot',text:'A newer answer from another page',actions:[]});
    browserState.set('transcript:EXAMPLE',JSON.stringify(current));
    window.listeners.pageshow({persisted:true});
    assert.equal(get('chat-log').children.length,5,'Back/forward restoration refreshes the cached page');
    assert.equal(get('chat-log').children[4].children[0].children[0].textContent,'A newer answer from another page');
    assert.equal(requests.length,1,'Back/forward restoration never resends the message');
  } else if(scenario==='preloaded-actions') {
    assert.equal(requests.length,0,'Preloading must not request actions or call the model');
    const show=(source=window.parent,origin='https://business.example')=>window.listeners.message({source,origin,data:{type:'V7_WIDGET_SHOW'}});
    show({},'https://business.example');show(window.parent,'https://unapproved.example');await flush();
    assert.equal(requests.length,0,'Foreign messages cannot start action discovery');
    show();await flush();assert.equal(requests.length,1);assert.equal(new URL(requests[0].url).pathname,'/chat/actions');
    show();await flush();assert.equal(requests.length,1,'Reopening does not repeat action discovery');
  } else if(scenario==='palette') {
    const s=body.style.values;
    for(const [surface,text] of [['--wbg','--wtext'],['--wpanel','--wpanel-text'],['--wfield','--wfield-text'],['--wme','--wme-text'],['--waccent','--waccent-text']]) {
      assert.ok(contrast(s[surface],s[text])>=4.5,`${surface} needs readable text`);
    }
    assert.equal(s['--wbg'],'#fafafa');assert.equal(s['--wpanel'],'#101010');
    assert.equal(s['--wpanel-text'],'#eeeeee','Readable custom text is retained');
    assert.equal(s['--wtext'],'#000000','Unreadable custom text receives a readable fallback');
  } else if(scenario.startsWith('navigation-')) {
    get('chat-input').value='Show products';await get('chat-form').fire('submit');
    const bubble=get('chat-log').children.at(-1).children[0];
    const link=bubble.children.find(child=>child.className==='msg__actions').children[0];
    assert.equal(link.href,'https://shop.example/products#catalog');assert.equal(link.target,'_blank');
    assert.equal(link.textContent,'See products');
    get('chat-input').value='Second conversation';await get('chat-form').fire('submit');
    assert.equal(storedToken,'second-conversation');
    await link.fire('click',{preventDefault(){throw new Error('Click reporting must preserve native navigation');}});
    await flush();
    assert.equal(link.textContent,'See products · Clicked');
    assert.match(link.getAttribute('aria-label'),/Clicked/);
    assert.equal(get('chat-log').children.at(-1).children[0].children[0].textContent,'You clicked: See products');
    const clickRequests=()=>requests.filter(item=>item.url==='/chat/navigation-click');
    assert.equal(clickRequests().length,1);
    const report=JSON.parse(clickRequests()[0].options.body);
    assert.equal(report.conversation_token,'synthetic-only','Each button retains its issued conversation identity');
    assert.equal(report.click_token,'issued-button-proof');assert.equal(report.tenant,'EXAMPLE');
    assert.equal(clickRequests()[0].options.keepalive,true);
    const count=get('chat-log').children.length;
    await link.fire('click');await flush();
    assert.equal(get('chat-log').children.length,count,'Repeated clicks do not duplicate the local activity row');
    assert.equal(clickRequests().length,scenario==='navigation-failure'?2:1);
    assert.equal(requests.filter(item=>item.url==='/chat_api').length,2,'Click reporting never starts an AI request');
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
  } else if(scenario==='pending-chat-draft') {
    get('chat-input').value='Original question';
    const response=get('chat-form').fire('submit');await flush();
    assert.equal(get('chat-status').textContent,'Getting a reply…');
    get('chat-input').value='A new draft typed while waiting';
    pending[0]({ok:false,status:503,json:async()=>({error:'Internal diagnostic must not reach the customer'})});await response;
    assert.equal(get('chat-input').value,'A new draft typed while waiting','A failed reply must preserve the next draft');
    assert.equal(get('chat-status').textContent,'');assert.equal(get('chat-send').disabled,false);
    assert.equal(get('chat-log').children.at(-1).children[0].children[0].textContent,'The message could not be completed. Please try again.');
  } else if(scenario==='pending-chat-focus') {
    get('chat-input').value='Original question';
    const response=get('chat-form').fire('submit');await flush();get('chat-action-name').focus();
    pending[0]({ok:true,json:async()=>({reply:'A helpful reply',conversation_token:'synthetic-only'})});await response;
    assert.equal(document.activeElement,get('chat-action-name'),'A reply must not pull focus from the request form');
    assert.equal(get('chat-status').textContent,'');
  } else if(scenario==='actions-unavailable-chat') {
    get('chat-input').value='When are you open?';await get('chat-form').fire('submit');
    assert.equal(get('chat-log').children.at(-1).children[0].children[0].textContent,'Our opening hours are 9am to 5pm.');
    assert.equal(get('chat-send').disabled,false);
  } else if(scenario.startsWith('chat-')) {
    get('chat-input').value='Original question';await get('chat-form').fire('submit');
    const message=get('chat-log').children.at(-1).children[0].children[0].textContent;
    if(scenario==='chat-paused') assert.match(message,/contact the business directly/);
    else if(scenario==='chat-rate-limit') assert.match(message,/wait a moment/);
    else if(scenario==='chat-expired') {assert.match(message,/session expired/);assert.equal(storedToken,'');}
    else if(scenario==='chat-cold-start') assert.match(message,/temporarily unavailable or starting up/);
    else if(scenario==='chat-provider-reference') assert.match(message,/Reference: a{24}/);
    else if(scenario==='chat-first-timeout') {
      assert.match(message,/took too long/);assert.equal(storedToken,'synthetic-only');
      const chat=requests.filter(item=>item.url==='/chat_api');assert.equal(chat.length,1);
      assert.equal(JSON.parse(chat[0].options.body).conversation_token,'synthetic-only');
    }
    else assert.equal(message,'The message could not be completed. Please try again.');
    assert.equal(get('chat-input').value,'Original question');assert.equal(get('chat-send').disabled,false);
    assert.equal(get('chat-status').textContent,'');assert.equal(utterances.length,0);
  } else if(scenario==='escape-close') {
    await get('dictate').fire('click');assert.equal(get('dictate').getAttribute('aria-pressed'),'true');
    let prevented=false;
    document.listeners.keydown({key:'Escape',defaultPrevented:false,preventDefault(){prevented=true;}});
    assert.equal(prevented,true);assert.equal(closeNotifications,1);assert.equal(get('dictate').getAttribute('aria-pressed'),'false');
    document.listeners.keydown({key:'Escape',defaultPrevented:true,preventDefault(){throw new Error('Already handled');}});
    assert.equal(closeNotifications,1,'An already-handled Escape must not close the widget again');
  } else if(scenario==='server-audio-wav') {
    await get('dictate').fire('click');await get('dictate').fire('click');await flush();
    const upload=requests.find(item=>item.url==='/chat/transcribe');assert.ok(upload);
    const file=upload.options.body.get('audio');assert.equal(file.type,'audio/wav');assert.equal(file.name,'message.wav');
    const bytes=await file.arrayBuffer(),data=new DataView(bytes);
    assert.equal(Buffer.from(bytes).subarray(0,4).toString(),'RIFF');assert.equal(Buffer.from(bytes).subarray(8,12).toString(),'WAVE');
    assert.equal(data.getUint16(20,true),1);assert.equal(data.getUint16(22,true),1);
    assert.equal(data.getUint32(24,true),16000);assert.equal(data.getUint16(34,true),16);
    assert.equal(data.getUint32(40,true),8);assert.equal(bytes.byteLength,52);
    assert.deepEqual([0,1,2,3].map(index=>data.getInt16(44+index*2,true)),[-32768,0,0,32767]);
    assert.equal(trackStops,1);assert.equal(audioCloses,1);
    pending[0]({ok:true,json:async()=>({text:'Please check this product'})});await flush();
    assert.equal(get('chat-input').value,'Please check this product');
    assert.equal(requests.filter(item=>item.url==='/chat_api').length,0,'Dictation still needs a separate Send action');
  } else if(['server-audio-too-long','server-audio-invalid','server-audio-decode-timeout'].includes(scenario)) {
    await get('dictate').fire('click');await get('dictate').fire('click');await flush();
    if(scenario==='server-audio-decode-timeout') {
      const timeout=[...timers.values()].find(timer=>timer.delay===10000);assert.ok(timeout);timeout.callback();await flush();
    }
    assert.equal(requests.filter(item=>item.url==='/chat/transcribe').length,0);
    assert.equal(trackStops,1);assert.equal(audioCloses,1);assert.equal(get('dictate').disabled,false);
    assert.match(get('voice-status').textContent,scenario==='server-audio-too-long'?/too long/:scenario==='server-audio-invalid'?/could not be read/:/conversion timed out/);
  } else if(scenario==='server-audio-decode-cancel') {
    await get('dictate').fire('click');await get('dictate').fire('click');await flush();
    get('chat-input').value='Typed instead';await get('chat-form').fire('submit');await flush();
    assert.equal(requests.filter(item=>item.url==='/chat/transcribe').length,0);
    assert.equal(audioCloses,1);assert.equal(get('dictate').disabled,false);
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
    assert.equal(get('chat-input').focusCalls || 0,0,'Late replies must not steal focus after the widget is hidden');
  } else if(scenario==='unsupported') {
    assert.equal(get('dictate').hidden,true);assert.equal(get('read-aloud').disabled,true);
    assert.match(get('voice-status').textContent,/type your message/);
    get('chat-input').value='Typed chat works';await get('chat-form').fire('submit');
    assert.equal(get('chat-send').disabled,false);assert.equal(get('chat-log').children.length,2);
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


@pytest.mark.parametrize("scenario", [
    "restore-chat", "preloaded-actions", "palette", "microphone", "playback", "server-cancel", "unsupported", "navigation-click", "navigation-failure",
    "late-playback-hidden", "late-playback-closed", "late-playback-pagehide",
    "server-permission-race", "server-stop-race",
    "launcher-close-native", "server-launcher-close", "late-playback-launcher",
    "pending-chat-draft", "pending-chat-focus", "chat-paused", "chat-rate-limit", "cross-tab", "cross-tab-concurrent", "cross-tab-blocked",
    "chat-expired", "chat-malformed", "chat-cold-start", "chat-provider-reference", "chat-first-timeout", "actions-unavailable-chat", "escape-close",
    "server-audio-wav", "server-audio-too-long", "server-audio-invalid",
    "server-audio-decode-timeout", "server-audio-decode-cancel",
])
def test_customer_widget_runtime(scenario):
    result = subprocess.run(
        [NODE, "-e", SCRIPT, scenario], cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("viewport_width,content_width", [(390, 375), (390, 390), (320, 305), (1024, 1009), (280, 265)])
def test_embed_launcher_notifies_its_widget_before_hiding(viewport_width, content_width):
    from routes.webchat_routes import _embed_javascript

    launcher_script = _embed_javascript("EXAMPLE", {"widget": {"allowed_origins": ["https://business.example"]}})
    harness = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const viewportWidth=Number(process.argv[1]),contentWidth=Number(process.argv[2]);
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
  hasAttribute(name){return Object.hasOwn(this.attributes,name);}
  set src(value){this.attributes.src=value;}
  get src(){return this.attributes.src;}
  appendChild(child){this.children.push(child);}
  addEventListener(name,callback){this.listeners[name]=callback;}
  focus(){}
}
const window={innerWidth:viewportWidth,location:{href:'https://business.example/'},listeners:{},addEventListener(name,callback){this.listeners[name]=callback;}};
const document={documentElement:{clientWidth:contentWidth},currentScript:{src:'https://widget.example/widget.js?tenant=EXAMPLE',dataset:{}},
  getElementById(){return null;},body:new Element('body'),createElement(type){
    const element=new Element(type);if(type==='div'&&!root)root=element;if(type==='button'&&!launcher)launcher=element;if(type==='iframe')frame=element;return element;
  }};
vm.runInNewContext(fs.readFileSync(0,'utf8'),{document,window,URL,console,setTimeout(){return 1;},clearTimeout(){}});
assert.equal(frame.style.width,Math.min(380,contentWidth-40)+'px','Frame width uses the space available without the scrollbar');
assert.ok(contentWidth-20-parseFloat(frame.style.width)>=20,'The frame keeps both 20px viewport gutters');
launcher.listeners.click();assert.equal(frame.style.display,'block');
window.innerWidth=250;document.documentElement.clientWidth=235;window.listeners.resize();
assert.equal(frame.style.width,'195px','An open frame adapts to a narrower viewport');
launcher.listeners.click();assert.equal(frame.style.display,'none');assert.equal(notifications.length,1);
window.innerWidth=390;document.documentElement.clientWidth=375;
launcher.listeners.click();root.listeners.keydown({key:'Escape'});assert.equal(frame.style.display,'none');assert.equal(notifications.length,2);
assert.equal(frame.style.width,'335px','Opening recalculates width even without a resize event');
launcher.listeners.click();window.listeners.message({origin:'https://unapproved.example',source:frame.contentWindow,data:{type:'V7_WIDGET_CLOSE'}});
assert.equal(frame.style.display,'block');assert.equal(notifications.length,2);
window.listeners.message({origin:'https://widget.example',source:frame.contentWindow,data:{type:'V7_WIDGET_CLOSE'}});
assert.equal(frame.style.display,'none');assert.equal(notifications.length,3);
"""
    result = subprocess.run(
        [NODE, "-e", harness, str(viewport_width), str(content_width)], cwd=ROOT, input=launcher_script,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
