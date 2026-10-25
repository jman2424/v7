"""Run the generated embed through pending, ready, failed and retried loads."""
import shutil
import subprocess

import pytest

from routes.webchat_routes import _embed_javascript


@pytest.mark.parametrize('scenario', ['ready', 'retry', 'close-pending', 'preload', 'data-saver', 'background', 'opt-out', 'restore-open'])
def test_embed_never_reveals_an_unready_frame(scenario):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for embed runtime checks')
    harness = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const scenario=process.argv[1],timers=new Map();let nextTimer=0;
class Element {
  constructor(type){this.type=type;this.children=[];this.attrs={};this.listeners={};
    this.style={set cssText(value){this.display=value.match(/display:([^;]+)/)?.[1];}};
    if(type==='iframe')this.contentWindow={postMessage(){}};
  }
  setAttribute(key,value){this.attrs[key]=value;}
  hasAttribute(key){return Object.hasOwn(this.attrs,key);}
  set src(value){this.attrs.src=value;}
  get src(){return this.attrs.src;}
  appendChild(child){this.children.push(child);}
  addEventListener(name,callback){this.listeners[name]=callback;}
  focus(){}
}
const body=new Element('body');
const document={body,documentElement:{clientWidth:375},
  currentScript:{src:'https://widget.example/widget.js?tenant=EXAMPLE',dataset:{}},
  getElementById(){return null;},createElement:type=>new Element(type)};
const window={innerHeight:800,location:{href:'https://business.example/'},listeners:{},
  addEventListener(name,callback){this.listeners[name]=callback;}};
const openKey='v7-widget-open:https://widget.example:EXAMPLE',stored=new Map();
if(scenario==='restore-open')stored.set(openKey,JSON.stringify({open:true,expires:Date.now()+3600000}));
if(scenario==='data-saver')window.navigator={connection:{saveData:true}};
if(scenario==='background')document.hidden=true;
if(scenario==='opt-out')document.currentScript.dataset.preload='false';
vm.runInNewContext(fs.readFileSync(0,'utf8'),{document,window,URL,sessionStorage:{getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)},
  setTimeout(callback,ms){assert.ok([1200,20000].includes(ms));timers.set(++nextTimer,callback);return nextTimer;},
  clearTimeout:id=>timers.delete(id)});
const root=body.children[0],[frame,launcher,loader]=root.children;
const text=loader.children[1],retry=loader.children[2];
const click=()=>launcher.listeners.click();
const ready=(id=new URL(frame.src).searchParams.get('v7_load'),origin='https://widget.example',source=frame.contentWindow)=>
  window.listeners.message({origin,source,data:{type:'V7_WIDGET_READY',loadId:id}});
if(scenario==='restore-open') {
  assert.equal(frame.style.display,'block','The requested chat remains open on the next page');
  ready();assert.equal(loader.style.display,'none');click();assert.equal(stored.has(openKey),false,'Closing clears automatic reopening');
} else {
assert.equal(frame.src,undefined,'A closed widget makes no iframe request');
assert.equal(timers.size,1);
if(['preload','data-saver','background','opt-out'].includes(scenario)) {
  const [id,callback]=[...timers.entries()][0];timers.delete(id);callback();
  if(scenario==='preload') {
    assert.ok(frame.src.includes('preload=1'));assert.equal(frame.style.display,'none');
    const warmed=frame.src;ready();assert.equal(loader.style.display,'none');
    click();assert.equal(frame.src,warmed);assert.equal(frame.style.visibility,'visible');
    assert.equal(timers.size,0,'A ready preloaded UI opens without a loading timer');
    launcher.listeners.pointerenter();assert.equal(frame.src,warmed);
  } else {
    assert.equal(frame.src,undefined,'Data saver, background and opt-out do not preload');
    click();assert.ok(frame.src,'Explicit opening still works');
  }
} else {
click();
const original=frame.src;
assert.equal(frame.style.display,'block');assert.equal(frame.style.visibility,'hidden');
assert.equal(loader.style.display,'flex');assert.match(text.textContent,/Loading/);
assert.equal(loader.style.width,frame.style.width);assert.equal(loader.attrs['aria-busy'],'true');
assert.equal(retry.hidden,true);
if(scenario==='ready') {
  ready('1','https://unapproved.example');ready('1','https://widget.example',{});ready('0');
  assert.equal(frame.style.visibility,'hidden','Wrong origins, windows and old loads cannot reveal the frame');
  ready();assert.equal(frame.style.visibility,'visible');assert.equal(loader.style.display,'none');
  assert.equal(timers.size,0);assert.equal(loader.attrs['aria-busy'],'false');
  click();click();assert.equal(frame.src,original,'Reopening keeps the conversation and iframe');
  assert.equal(loader.style.display,'none');assert.equal(timers.size,0);
} else if(scenario==='retry') {
  [...timers.values()][0]();assert.match(text.textContent,/taking longer/);assert.equal(retry.hidden,false);
  retry.listeners.click();assert.notEqual(frame.src,original);assert.match(text.textContent,/Loading/);
  assert.equal(retry.hidden,true);ready('1');assert.equal(frame.style.visibility,'hidden','A late reply from the previous load is ignored');
  frame.listeners.error();assert.equal(retry.hidden,false);assert.equal(timers.size,0);
  retry.listeners.click();ready();assert.equal(loader.style.display,'none');assert.equal(frame.style.visibility,'visible');
} else {
  click();assert.equal(frame.style.display,'none');assert.equal(loader.style.display,'none');assert.equal(timers.size,0);
  ready();assert.equal(frame.style.display,'none','Readiness cannot reopen a closed widget');
  click();assert.equal(frame.src,original);assert.equal(frame.style.visibility,'visible');assert.equal(timers.size,0);
}
}
}
"""
    result = subprocess.run(
        [node, '-e', harness, scenario], input=_embed_javascript('EXAMPLE', {}),
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
