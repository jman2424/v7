const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../../dashboard/static/js/widget-session.js'),'utf8');
function setup(){const window={};vm.runInNewContext(code,{window,URL});const data=new Map();return {window,data,storage:{getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)}};}
test('same tenant and token restore messages, buttons, clicked state and draft after navigation',()=>{
 const {window,data,storage}=setup();let now=1000;const first=window.V7ChatSession(storage,'ALPHA',()=>now);
 first.write('signed-one',{messages:[{from:'me',text:'My Polo'},{from:'bot',text:'This is an estimate.',actions:[{type:'navigate',label:'Services',url:'https://business.example/services',click_token:'signed-click',clicked:true}]}],draft:'What about polishing?',pending:''});
 const saved=window.V7ChatSession(storage,'ALPHA',()=>now).read('signed-one');
 assert.equal(saved.messages[1].actions[0].clicked,true);assert.equal(saved.messages[0].text,'My Polo');assert.equal(saved.draft,'What about polishing?');
 assert.equal(window.V7ChatSession(storage,'BETA',()=>now).read('signed-one'),null);
 assert.equal(window.V7ChatSession(storage,'ALPHA',()=>now).read('different-session'),null);assert.equal(data.size,0);
});
test('expired, corrupt, oversized and unsafe stored state fails closed without executing content',()=>{
 const {window,data,storage}=setup();let now=1000;const state=window.V7ChatSession(storage,'ALPHA',()=>now);
 const credentialUrl=new URL('https://example.test/');
 credentialUrl.username='fixture-user';credentialUrl.password='fixture-password';
 state.write('token',{messages:[{from:'bot',text:'<script>test</script>',actions:[{type:'navigate',url:'javascript:alert(1)',label:'Unsafe'},{type:'navigate',url:credentialUrl.href,label:'Credentials'}]}]});
 assert.equal(state.read('token').messages[0].actions.length,0);
 now+=86400001;assert.equal(state.read('token'),null);
 for(const raw of ['{invalid','x'.repeat(96001),JSON.stringify({version:1,token:'token',expires:now+86400001,messages:[]})]){data.set('transcript:ALPHA',raw);assert.equal(state.read('token'),null);}
});
test('storage is bounded and unavailable storage never blocks conversation',()=>{
 const {window,data,storage}=setup();const state=window.V7ChatSession(storage,'ALPHA',()=>1000);
 state.write('token',{messages:Array.from({length:60},()=>({from:'bot',text:'a'.repeat(4000)})),draft:'d'.repeat(8000),pending:'Do not automatically resend'});
 const raw=data.get('transcript:ALPHA'),saved=state.read('token');assert.ok(raw.length<=96000);assert.ok(saved.messages.length<=40);assert.equal(saved.draft.length,4000);assert.equal(saved.pending,'Do not automatically resend');
 state.write('token',{messages:Array.from({length:60},()=>({from:'bot',text:'م'.repeat(4000)}))});
 assert.ok(Buffer.byteLength(data.get('transcript:ALPHA'),'utf8')<=96000,'Unicode transcripts obey the byte bound');
 const blocked=window.V7ChatSession({getItem(){throw Error('blocked')},setItem(){throw Error('full')},removeItem(){throw Error('blocked')}},'ALPHA');
 assert.equal(blocked.read('token'),null);assert.doesNotThrow(()=>blocked.write('token',{messages:[]}));assert.doesNotThrow(()=>blocked.clear());
});

test('open tabs share bounded chat state only within the same business and host scope',()=>{
 const peers=new Map();
 class Channel {
  constructor(name){this.name=name;(peers.get(name)||peers.set(name,new Set()).get(name)).add(this);}
  postMessage(data){for(const peer of peers.get(this.name))if(peer!==this)peer.onmessage?.({data});}
  close(){peers.get(this.name).delete(this);}
 }
 const first=setup(),second=setup(),other=setup();
 const one=first.window.V7ChatSession(first.storage,'ALPHA');
 one.write('signed-one',{messages:[{from:'me',text:'My car is a Polo'},{from:'bot',text:'Small car estimate'}],draft:'private draft'});
 const snapshot=()=>{const saved=one.read('signed-one');return JSON.stringify({version:1,token:'signed-one',expires:saved.expires,messages:saved.messages,draft:'',pending:''});};
 const a=first.window.V7ChatTabs('ALPHA:https://business.example',snapshot,()=>{},Channel);
 const received=[];
 const b=second.window.V7ChatTabs('ALPHA:https://business.example',()=>'',(token,raw)=>received.push({token,state:JSON.parse(raw)}),Channel);
 assert.equal(received.length,1);assert.equal(received[0].token,'signed-one');assert.equal(received[0].state.messages[0].text,'My car is a Polo');
 assert.equal(received[0].state.draft,'');assert.equal(received[0].state.pending,'');
 const wrong=[];
 const c=other.window.V7ChatTabs('BETA:https://business.example',()=>'',(...args)=>wrong.push(args),Channel);
 const d=other.window.V7ChatTabs('ALPHA:https://different.example',()=>'',(...args)=>wrong.push(args),Channel);
 one.write('signed-one',{messages:[{from:'bot',text:'Polishing starts from an estimate.'}]});a.publish();
 assert.equal(received.at(-1).state.messages[0].text,'Polishing starts from an estimate.');assert.equal(wrong.length,0);
 const bad=new Channel('v7-chat:ALPHA:https://business.example');const before=received.length;
 for(const value of ['{broken','x'.repeat(96001),JSON.stringify({version:1,token:'signed-one',expires:1,messages:[]})])bad.postMessage({type:'state',value});
 assert.equal(received.length,before);a.close();b.close();c.close();d.close();bad.close();
 assert.doesNotThrow(()=>second.window.V7ChatTabs('ALPHA',()=>'',()=>{},class{constructor(){throw Error('blocked');}}).publish());
});

test('concurrent and delayed tab snapshots merge without deleting completed exchanges or clicks',()=>{
 const {window}=setup();const merge=window.V7MergeChatRows;
 const old={id:'message:1',at:1,from:'bot',text:'Choose a service',actions:[{type:'navigate',url:'https://business.example/services',label:'Services',clicked:false}]};
 const a=[old,{id:'message:2',at:2,from:'me',text:'Polishing?'},{id:'message:4',at:4,from:'bot',text:'Polishing estimate'}];
 const b=[{...old,actions:[{...old.actions[0],clicked:true}]},{id:'message:3',at:3,from:'me',text:'Coating?'},{id:'message:5',at:5,from:'bot',text:'Coating estimate'}];
 const both=merge(a,b);assert.deepEqual(Array.from(both,row=>row.id),['message:1','message:2','message:3','message:4','message:5']);
 assert.equal(both[0].actions[0].clicked,true);
 const delayed=merge(both,[old]);assert.equal(delayed.length,5);assert.equal(delayed[0].actions[0].clicked,true);
 assert.equal(merge(both,both).length,5,'Repeated peer state does not duplicate messages');
});

test('an expired in-memory conversation cannot be renewed by another tab requesting state',()=>{
 const {window,storage}=setup();let now=1000;const session=window.V7ChatSession(storage,'ALPHA',()=>now);
 const state={messages:[{from:'bot',text:'Old conversation'}]};
 session.write('old-token',state);now+=86400001;
 assert.equal(session.write('old-token',state),undefined);
 assert.equal(session.write('old-token',state),undefined,'Repeated publication cannot renew a retired token');
 assert.equal(session.read('old-token'),null);
 assert.ok(session.write('new-token',{messages:[]}),'A genuinely new conversation still works');
});
