"""Closing a preference panel must not grant optional cookie consent."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
pytestmark = pytest.mark.skipif(not NODE, reason='Node is required')

SCRIPT = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const scenario=process.argv[1],cookies=new Map(),listeners=new Map();
if(scenario==='saved')cookies.set('v7_preferences','all');
cookies.set('session','synthetic-session');
const node=()=>({hidden:true,dataset:{},style:{},attributes:{},events:{},focused:false,
 addEventListener(name,callback){this.events[name]=callback;},
 setAttribute(name,value){this.attributes[name]=value;},focus(){this.focused=true;},
 getBoundingClientRect(){return {height:180};}});
const banner=node(),opener=node(),close=node(),essential=node(),all=node();
essential.dataset.preferences='essential';all.dataset.preferences='all';
banner.querySelector=()=>close;
const document={currentScript:{src:'https://synthetic.test/static/js/ui-i18n.js'},
 documentElement:{lang:'en',dir:'ltr'},body:{style:{paddingBottom:'24px'}},
 getElementById:()=>banner,
 querySelectorAll(selector){return {
  '[data-open-cookie-preferences]':[opener],'[data-close-cookie-preferences]':[close],
  '[data-preferences]':[essential,all],'[data-language-picker]':[],'[data-i18n]':[]
 }[selector]||[];},
 addEventListener(name,callback){listeners.set(name,callback);}};
Object.defineProperty(document,'cookie',{get:()=>[...cookies].map(([k,v])=>k+'='+v).join('; '),
 set:value=>{const [pair,...attributes]=value.split('; '),[name,content]=pair.split('=');
  if(attributes.includes('Max-Age=0'))cookies.delete(name);else cookies.set(name,content);}});
const context=vm.createContext({document,URL,navigator:{language:'en-GB'},location:{protocol:'https:'},
 window:{dispatchEvent(){}},CustomEvent:class{},fetch:async()=>({ok:false}),
 ResizeObserver:class{observe(){}}});
vm.runInContext(fs.readFileSync('dashboard/static/js/ui-i18n.js','utf8'),context);
if(scenario==='saved')assert.equal(banner.hidden,true);
else assert.equal(banner.hidden,false);
assert.equal(document.body.style.paddingBottom,'24px');
if(scenario==='dismiss') {
 close.events.click();assert.equal(banner.hidden,true);assert.equal(cookies.has('v7_preferences'),false);
 opener.events.click();assert.equal(banner.hidden,false);assert.equal(close.focused,true);
 assert.equal(document.body.style.paddingBottom,'24px');
 listeners.get('keydown')({key:'Escape'});assert.equal(banner.hidden,true);assert.equal(opener.focused,true);
 assert.equal(cookies.has('v7_preferences'),false);
} else if(scenario==='essential') {
 cookies.set('v7_language','fr');essential.events.click();assert.equal(banner.hidden,true);
 assert.equal(cookies.get('v7_preferences'),'essential');assert.equal(cookies.has('v7_language'),false);
} else if(scenario==='optional') {
 all.events.click();assert.equal(cookies.get('v7_preferences'),'all');assert.equal(cookies.get('v7_language'),'en');
 opener.events.click();close.events.click();assert.equal(cookies.get('v7_preferences'),'all');
} else if(scenario==='saved') {
 opener.events.click();listeners.get('keydown')({key:'Escape'});
 assert.equal(cookies.get('v7_preferences'),'all');
}
assert.equal(cookies.get('session'),'synthetic-session');
assert.equal(document.body.style.paddingBottom,'24px');
"""


@pytest.mark.parametrize('scenario', ['dismiss', 'essential', 'optional', 'saved'])
def test_home_cookie_preferences_preserve_consent_and_security(scenario):
    result = subprocess.run([NODE, '-e', SCRIPT, scenario], cwd=ROOT, text=True,
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
