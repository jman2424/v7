const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.join(__dirname,'../..');
const dictionary=JSON.parse(fs.readFileSync(path.join(root,'dashboard/static/i18n/home.json'),'utf8'));
test('homepage switches all four languages, restores English, preserves amounts and markup',async()=>{
 let language='en';const events={};
 const parent=(excluded=false,source='')=>({dataset:{i18nSource:source},closest:selector=>selector==='[data-i18n]'?(source?{dataset:{i18nSource:source}}:null):(excluded?{}:null)});
 const nodes=[{nodeValue:'Request a demo',parentElement:parent()},
 {nodeValue:'  £199 one-time setup  ',parentElement:parent()},
 {nodeValue:'The right plan.',parentElement:parent(false,'The right plan.')},
 {nodeValue:'Untouched executable content',parentElement:parent(true)}];
 const title={tagName:'TITLE',textContent:'Vertex Seven | V7 Agents — AI chatbot for business',matches:()=>false,hasAttribute:()=>false};
 const iframe={tagName:'IFRAME',values:{title:'Chat with Vertex Seven'},matches:()=>false,hasAttribute:n=>n==='title',getAttribute:n=>iframe.values[n],setAttribute:(n,v)=>{assert.equal(n,'title');iframe.values[n]=v;}};
 const document={currentScript:{src:'https://vertex-seven.com/static/js/home-i18n.js'},body:{},
   createTreeWalker(){let i=0;return {nextNode:()=>nodes[i++]||null};},querySelectorAll:()=>[title,iframe]};
 const window={V7UI:{language:()=>language,t:s=>s},addEventListener:(n,fn)=>events[n]=fn};
 vm.runInNewContext(fs.readFileSync(path.join(root,'dashboard/static/js/home-i18n.js'),'utf8'),{document,window,URL,fetch:async()=>({ok:true,json:async()=>dictionary})});
 await new Promise(resolve=>setImmediate(resolve));
 for(language of ['es','fr','ar','en']){
   nodes[2].nodeValue='A marker recreated by the shared translator';events['v7-language-changed']();
   assert.equal(nodes[0].nodeValue,language==='en'?'Request a demo':dictionary[language]['Request a demo']);
   assert.equal(nodes[1].nodeValue,language==='en'?'  £199 one-time setup  ':'  '+dictionary[language]['£{0} one-time setup'].replace('{0}','199')+'  ');
   assert.equal(nodes[2].nodeValue,language==='en'?'The right plan.':dictionary[language]['The right plan.']);
   assert.equal(nodes[3].nodeValue,'Untouched executable content');
   assert.equal(iframe.values.title,language==='en'?'Chat with Vertex Seven':dictionary[language]['Chat with Vertex Seven']);
 }
 assert.equal(title.textContent,'Vertex Seven | V7 Agents — AI chatbot for business');
});
