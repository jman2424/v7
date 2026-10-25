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
 state.write('token',{messages:[{from:'bot',text:'<script>test</script>',actions:[{type:'navigate',url:'javascript:alert(1)',label:'Unsafe'},{type:'navigate',url:'https://user:password@example.test/',label:'Credentials'}]}]});
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
