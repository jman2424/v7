"""Cleared transcripts cannot be restored by delayed or replayed peer messages."""
import subprocess

from tests.test_widget_runtime import NODE, ROOT, pytestmark  # noqa: F401


def test_bounded_reset_fence_replay_and_timestamp_validation():
    script = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let now=1000000000, channel, resets=[], received=[];
class Channel {constructor(name){channel=this;this.name=name;this.sent=[];}postMessage(data){this.sent.push(data);}}
const window={BroadcastChannel:Channel};
vm.runInNewContext(fs.readFileSync('dashboard/static/js/widget-session.js','utf8'),
  {window,URL,TextEncoder,Date:{now:()=>now}});
const tabs=window.V7ChatTabs('TENANT|https://shop.example',()=>null,(token)=>received.push(token),Channel,
  token=>{resets.push(token);return token==='old';});
const send=data=>channel.onmessage({data});
const state=(token,birth)=>({type:'state',value:JSON.stringify({version:1,token,expires:birth+86400000,
  messages:[{id:'message:1',at:birth,from:'me',text:'Synthetic',actions:[]}],draft:'',pending:''})});
for(const at of [undefined,null,'now',NaN,Infinity,now-86400001,now+1001])send({type:'reset',token:'old',at});
assert.equal(resets.length,0,'Missing or malformed reset time is not trusted');
send({type:'reset',token:'old',at:now});
assert.deepEqual(resets,['old']);
for(let i=0;i<41;i++)send({type:'reset',token:'foreign:'+i,at:now});
send(state('old',now-2000));assert.equal(received.length,0,'Fence survives bounded tombstone eviction');
now+=2000;send(state('new',now));assert.deepEqual(received,['new']);
send({type:'reset',token:'foreign',at:now});
send(state('new',now-1000));assert.equal(received.length,2,'Foreign reset cannot age out the active conversation');
send({type:'request'});
const replay=channel.sent.filter(row=>row.type==='reset');
assert.ok(replay.length<=40 && replay.every(row=>row.at<=now),'Replay retains original reset time');
tabs.reset('new');send(state('new',now));assert.equal(received.length,2,'Local reset retires its own token');
"""
    result = subprocess.run([NODE, '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
