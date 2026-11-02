const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ts=require('../node_modules/typescript');
const test=require('node:test');
function moduleFor(name){
 const source=fs.readFileSync(path.join(__dirname,'../src/lib/'+name+'.ts'),'utf8');
 const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,esModuleInterop:true}}).outputText;
 const scope={exports:{},URLSearchParams,require:()=>JSON.parse(fs.readFileSync(path.join(__dirname,'../../service/console_navigation.json'),'utf8'))};
 vm.runInNewContext(compiled,scope);return scope.exports;
}
const architecture=moduleFor('workspaceArchitecture');
const inbox=moduleFor('conversationInbox');
test('unsaved form coordination covers tenant changes without storing content or repeating dialogs',()=>{
 const drafts=moduleFor('draftNavigation');let dirty=false;
 const remove=drafts.registerDraft(()=>dirty);
 assert.equal(drafts.hasUnsavedDrafts(),false);dirty=true;assert.equal(drafts.hasUnsavedDrafts(),true);
 assert.equal(drafts.beginDraftPrompt(),true);assert.equal(drafts.beginDraftPrompt(),false);
 drafts.approveDraftNavigation('https://example.test/console/home?tenant=FIRST');
 assert.equal(drafts.navigationApproved('https://example.test/console/home?tenant=FIRST'),true);
 assert.equal(drafts.navigationApproved('https://example.test/console/home?tenant=SECOND'),false);
 drafts.finishDraftPrompt();assert.equal(drafts.navigationApproved('https://example.test/console/home?tenant=FIRST'),false);
 remove();assert.equal(drafts.hasUnsavedDrafts(),false);
});
test('six workspaces retain every legacy capability and tenant context',()=>{
 assert.deepEqual(Array.from(architecture.workspaces.map(item=>item.id)),['home','business','customers','channels','billing','settings']);
 for(const workspace of architecture.workspaces){for(const view of workspace.views){
   const location=architecture.resolveWorkspace(workspace.id,view.id);
   assert.equal(location.section,view.section);
   const url=new URL(architecture.workspaceHref('/console',workspace.id,view.id,'BUSINESS_A'),'https://example.test');
   assert.equal(url.searchParams.get('tenant'),'BUSINESS_A');assert.equal(url.searchParams.get('view'),view.id);
 }}
 assert.equal(architecture.sectionHref('/console','test','FIRST'),'/console/channels?tenant=FIRST&view=website&panel=test');
 assert.equal(architecture.sectionHref('/console','implementation','FIRST'),'/console/channels?tenant=FIRST&view=website&panel=install');
 assert.equal(architecture.resolveWorkspace('operations').panel,'approvals');
 assert.equal(architecture.legacyLocation('platform').workspace,'platform');
 assert.equal(architecture.workspaceAllowed('platform',false),false);
 assert.equal(architecture.workspaceAllowed('platform',true),true);
 assert.equal(architecture.workspaceAllowed('business',false),true);
 assert.equal(architecture.workspaceAllowed('unknown',true),false);
});
const message=(id,ref,text,channel='web')=>({id,conversation_ref:ref,text,channel,event_type:id%2?'msg_in':'msg_out',ts_utc:'2026-11-02T10:00:00Z'});
test('inbox keeps genuine conversation history chronological and searches full loaded thread',()=>{
 const threads=inbox.conversationThreads([message(4,'second','Other reply'),message(3,'second','Second customer'),message(2,'first','Answer'),message(1,'first','Pricing question')],'','pricing');
 assert.equal(threads.length,1);assert.deepEqual(Array.from(threads[0].messages.map(row=>row.id)),[1,2]);assert.equal(threads[0].title,'Pricing question');
});
test('inbox never merges legacy records, channels or separate customers',()=>{
 const rows=[message(1,null,'Legacy'),message(2,null,'Legacy reply'),message(3,'same','Web'),message(4,'same','Email','email'),message(5,'other','Other')];
 assert.equal(inbox.conversationThreads(rows).length,5);
 assert.equal(inbox.conversationThreads(rows,'email').length,1);
 assert.equal(inbox.conversationThreads(rows,'','missing').length,0);
});
