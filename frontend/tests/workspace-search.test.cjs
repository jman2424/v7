const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const test=require('node:test');
const vm=require('node:vm');
const ts=require('../node_modules/typescript');

function searchWith(fetch, globals={}){
  const source=fs.readFileSync(path.join(__dirname,'../src/lib/workspaceSearch.ts'),'utf8');
  const context={exports:{},fetch,URLSearchParams,...globals};
  vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context);
  return context.exports;
}
const page=key=>({key,label:key,href:'/console/test?tenant=A',keywords:'',description:'',reload:false});

test('record search scopes every request to the selected business and the visible pages',async()=>{
  const calls=[], results=[];
  const search=searchWith(async url=>{
    calls.push(new URL(url,'https://example.test'));
    return {ok:true,json:async()=>({categories:[{name:'Garden',items:[{sku:'42',name:'Purple tulips'}]}]})};
  });
  const failed=await search.loadSearchRecords([page('catalog'),page('pipeline')],'A','',new AbortController().signal,rows=>results.push(...rows),false);
  assert.equal(failed,false);assert.equal(calls.length,1);
  assert.equal(calls[0].pathname,'/admin/api/catalog');assert.equal(calls[0].searchParams.get('tenant'),'A');
  assert.equal(results[0].label,'Purple tulips');assert.ok(results[0].keywords.includes('Garden'));
  assert.equal(new URL(results[0].href,'https://example.test').hash,'#'+search.recordAnchor('catalog','42'));
});

test('message search queries retained history and a cancelled response cannot add results',async()=>{
  let finish, url;
  const controller=new AbortController();
  const search=searchWith(async address=>{
    url=new URL(address,'https://example.test');
    return {ok:true,json:()=>new Promise(resolve=>{finish=resolve})};
  });
  const records=[];
  const pending=search.loadSearchRecords([page('conversations'),page('catalog')],'B','',controller.signal,rows=>records.push(...rows),false,'late order');
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(url.pathname,'/admin/api/conversations');assert.equal(url.searchParams.get('q'),'late order');
  assert.equal(url.searchParams.get('period'),'all');
  controller.abort();finish({messages:[{id:2,text:'late order'}]});
  await pending;assert.deepEqual(records,[]);
});


test('search arrival expands the destination, focuses it and honours reduced motion',()=>{
  class Details {}
  for(const reduced of [true,false]){
    const parent=new Details();
    let focused=false,scroll,animated=false;
    const node={parentElement:parent,tabIndex:0,focus(options){focused=options.preventScroll;},
      scrollIntoView(options){scroll=options;},animate(){animated=true;}};
    const search=searchWith(null,{HTMLDetailsElement:Details,window:{matchMedia:()=>({matches:reduced})},
      getComputedStyle:()=>({backgroundColor:'white'})});
    search.focusSearchDestination(node);
    assert.ok(parent.open && focused);
    assert.equal(node.tabIndex,0);
    assert.equal(scroll.block,'nearest');
    assert.equal(scroll.behavior,reduced?'instant':'smooth');
    assert.equal(animated,!reduced);
  }
});

test('support and module records link to the specific row on its permitted page',async()=>{
  const results=[],urls=[];
  const search=searchWith(async address=>{
    const url=new URL(address,'https://example.test');urls.push(url);
    const data=url.pathname==='/billing/support'?{requests:[{id:'ref7',kind:'setup',message:'Need a callback'}]}:
      url.pathname==='/admin/api/agent-modules'?{modules:[{id:'email',label:'Email drafting'}]}:{};
    return {ok:true,json:async()=>data};
  });
  await search.loadSearchRecords([page('subscription'),page('agent')],'A','',new AbortController().signal,rows=>results.push(...rows),false);
  assert.equal(urls.length,3);assert.ok(urls.every(url=>url.searchParams.get('tenant')==='A'));
  const support=results.find(row=>row.key===search.recordAnchor('support','ref7'));
  assert.ok(support.href.endsWith('#'+support.key));assert.ok(support.keywords.includes('Need a callback'));
  const module=results.find(row=>row.key===search.recordAnchor('agent','email'));
  assert.equal(module.label,'Email drafting');assert.ok(module.href.endsWith('#'+module.key));
});
