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
if(['saved','legacy','withdraw'].includes(scenario))cookies.set('v7_preferences','all');
if(scenario==='saved')cookies.set('v7_analytics_consent','v1%3Adenied');
if(scenario==='withdraw')cookies.set('v7_analytics_consent','v1%3Agranted');
cookies.set('session','synthetic-session');
cookies.set('v7_trusted_device','synthetic-device-proof');
const node=()=>({hidden:true,checked:false,dataset:{},style:{},attributes:{},events:{},focused:false,
 addEventListener(name,callback){this.events[name]=callback;},
 setAttribute(name,value){this.attributes[name]=value;},focus(){this.focused=true;},
 getBoundingClientRect(){return {height:180};}});
const banner=node(),opener=node(),close=node(),essential=node(),all=node(),languageChoice=node(),analyticsChoice=node();
essential.dataset.preferences='essential';all.dataset.preferences='all';
banner.querySelector=selector=>({'[data-close-cookie-preferences]':close,
 '[data-consent-language]':languageChoice,'[data-consent-analytics]':analyticsChoice}[selector]||null);
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
 window:{dispatchEvent(){}},Event:class{},CustomEvent:class{},fetch:async()=>({ok:false}),
 ResizeObserver:class{observe(){}}});
vm.runInContext(fs.readFileSync('dashboard/static/js/ui-i18n.js','utf8'),context);
if(['saved','withdraw'].includes(scenario))assert.equal(banner.hidden,true);
else assert.equal(banner.hidden,false);
assert.equal(document.body.style.paddingBottom,'24px');
if(scenario==='dismiss') {
 close.events.click();assert.equal(banner.hidden,true);assert.equal(cookies.has('v7_preferences'),false);
 opener.events.click();assert.equal(banner.hidden,false);assert.equal(close.focused,true);
 assert.equal(document.body.style.paddingBottom,'24px');
 listeners.get('keydown')({key:'Escape'});assert.equal(banner.hidden,true);assert.equal(opener.focused,true);
 assert.equal(cookies.has('v7_preferences'),false);
 assert.equal(cookies.has('v7_analytics_consent'),false);
} else if(scenario==='essential') {
 cookies.set('v7_language','fr');essential.events.click();assert.equal(banner.hidden,true);
 assert.equal(cookies.get('v7_preferences'),'essential');assert.equal(cookies.has('v7_language'),false);
 assert.equal(cookies.get('v7_analytics_consent'),'v1%3Adenied');
} else if(scenario==='optional') {
 languageChoice.checked=true;
 all.events.click();assert.equal(cookies.get('v7_preferences'),'all');assert.equal(cookies.get('v7_language'),'en');
 assert.equal(cookies.get('v7_analytics_consent'),'v1%3Adenied');
 opener.events.click();close.events.click();assert.equal(cookies.get('v7_preferences'),'all');
} else if(scenario==='analytics') {
 analyticsChoice.checked=true;
 all.events.click();assert.equal(cookies.get('v7_preferences'),'essential');
 assert.equal(cookies.has('v7_language'),false);
 assert.equal(cookies.get('v7_analytics_consent'),'v1%3Agranted');
} else if(scenario==='legacy') {
 assert.equal(languageChoice.checked,true);assert.equal(analyticsChoice.checked,false);
 close.events.click();assert.equal(cookies.get('v7_preferences'),'all');
 assert.equal(cookies.has('v7_analytics_consent'),false);
} else if(scenario==='withdraw') {
 cookies.set('_ga','synthetic-analytics-id');cookies.set('_ga_TEST123456','synthetic-analytics-session');
 opener.events.click();assert.equal(analyticsChoice.checked,true);
 analyticsChoice.checked=false;all.events.click();
 assert.equal(cookies.get('v7_analytics_consent'),'v1%3Adenied');
 assert.equal(cookies.has('_ga'),false);assert.equal(cookies.has('_ga_TEST123456'),false);
} else if(scenario==='saved') {
 opener.events.click();listeners.get('keydown')({key:'Escape'});
 assert.equal(cookies.get('v7_preferences'),'all');
}
assert.equal(cookies.get('session'),'synthetic-session');
assert.equal(cookies.get('v7_trusted_device'),'synthetic-device-proof');
assert.equal(document.body.style.paddingBottom,'24px');
"""


@pytest.mark.parametrize('scenario', ['dismiss', 'essential', 'optional', 'saved', 'analytics', 'legacy', 'withdraw'])
def test_home_cookie_preferences_preserve_consent_and_security(scenario):
    result = subprocess.run([NODE, '-e', SCRIPT, scenario], cwd=ROOT, text=True,
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
