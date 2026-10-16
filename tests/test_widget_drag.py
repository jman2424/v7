"""Run the actual generated embed against a small pointer-capable DOM."""
import shutil
import subprocess

import pytest

from routes.webchat_routes import _embed_javascript


def test_embed_drag_and_keyboard_keep_chat_visible(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for embed runtime checks")
    script = tmp_path / "embed.js"
    script.write_text(_embed_javascript("EXAMPLE", {}), encoding="utf-8")
    harness = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
class Element {
  constructor(){this.style={};this.listeners={};this.children=[];this.attrs={};this.capture=null;}
  appendChild(el){this.children.push(el);}
  setAttribute(k,v){this.attrs[k]=v;}
  hasAttribute(k){return Object.hasOwn(this.attrs,k);}
  set src(value){this.attrs.src=value;}
  get src(){return this.attrs.src;}
  addEventListener(k,fn){(this.listeners[k] ||= []).push(fn);}
  fire(k,e={}){for(const fn of this.listeners[k] || []) fn(e);}
  setPointerCapture(id){this.capture=id;}
  hasPointerCapture(id){return this.capture===id;}
  releasePointerCapture(){this.capture=null;}
  focus(){}
  getBoundingClientRect(){const left=parseFloat(this.style.left)||560,top=parseFloat(this.style.top)||700;
    return {left:this.style.left==='0px'?0:left,top:this.style.top==='0px'?0:top,width:220,height:44,
      bottom:(this.style.top==='0px'?0:top)+44};}
}
const body=new Element();
const document={currentScript:{src:'https://widget.example/embed.js',dataset:{}},body,
  documentElement:{clientWidth:800},getElementById(){return null;},createElement(){return new Element();}};
const window={innerHeight:800,location:{href:'https://business.example/'},listeners:{},
  addEventListener(k,fn){(this.listeners[k] ||= []).push(fn);}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{document,window,URL,Math});
const root=body.children[0],frame=root.children[0],launcher=root.children[1];
// This DOM mock does not parse CSS declarations assigned through cssText.
frame.style.display='none';
assert.equal(launcher.style.touchAction,'none');
const pointer=(x,y,extra={})=>({pointerId:1,isPrimary:true,button:0,clientX:x,clientY:y,...extra});
launcher.fire('pointerdown',pointer(600,720));
launcher.fire('pointermove',pointer(602,722));
launcher.fire('pointerup',pointer(602,722));
launcher.fire('click');assert.equal(frame.style.display,'block');
launcher.fire('pointerdown',pointer(600,720));
launcher.fire('pointermove',pointer(-100,-100));
assert.equal(root.style.left,'0px');assert.equal(root.style.top,'0px');
assert.equal(frame.style.top,'56px');assert.equal(frame.style.height,'620px');
launcher.fire('pointerup',pointer(-100,-100));launcher.fire('click');
assert.equal(frame.style.display,'block');assert.equal(frame.style.pointerEvents,'');
launcher.fire('click');assert.equal(frame.style.display,'none');
let prevented=false;
launcher.fire('keydown',{altKey:true,key:'ArrowRight',preventDefault(){prevented=true;}});
assert.equal(root.style.left,'24px');assert.equal(prevented,true);
launcher.fire('pointerdown',pointer(24,0));
launcher.fire('pointermove',pointer(900,900));
launcher.fire('pointercancel',pointer(900,900));
assert.equal(root.style.left,'580px');assert.equal(root.style.top,'756px');
assert.equal(frame.style.bottom,'56px');assert.equal(frame.style.pointerEvents,'');
document.documentElement.clientWidth=320;window.innerHeight=480;
for(const fn of window.listeners.resize) fn();
assert.equal(root.style.left,'100px');assert.equal(root.style.top,'436px');
assert.equal(frame.style.width,'280px');assert.equal(frame.style.left,'-60px');
assert.equal(frame.style.height,'424px');
launcher.fire('pointerdown',pointer(100,436,{isPrimary:false}));
launcher.fire('pointermove',pointer(0,0));assert.equal(root.style.left,'100px');
"""
    result = subprocess.run([node, "-e", harness, str(script)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
