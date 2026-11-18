const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const lib=path.resolve(__dirname,'../src/lib');

test('every workspace view contributes destinations from its actual components',async()=>{
 const {sectionIndexPlugin}=await import('../scripts/section-index.mjs');
 const plugin=sectionIndexPlugin(lib);
 const entries=JSON.parse(plugin.load.call({addWatchFile(){}},plugin.resolveId('virtual:v7-section-index')).slice('export default '.length));
 const routes=require('../../service/console_navigation.json');
 for(const group of [...routes.workspaces,routes.platform])for(const view of group.views){
   assert.ok(entries.some(e=>e.workspace===group.id && e.view===view.id),group.id+'/'+view.id);
 }
 const title=(name,section)=>entries.find(e=>e.title===name&&e.section===section);
 const rest=title('REST API connection','integrations'), token=title('Token endpoint','integrations');
 assert.equal(title('API base URL','integrations').context,'REST API connection');
 assert.equal(rest.view,'apps');assert.equal(rest.workspace,'settings');assert.equal(token.open.length,1);
 const filename=path.join(lib,'ConnectionSettings.svelte');
 const {code}=plugin.transform(fs.readFileSync(filename,'utf8'),filename);
 for(const id of [rest.id,token.id,...token.open])assert.ok(code.includes('data-workspace-section="'+id+'"'));
 assert.equal(title('Welcome message','website').panel,'appearance');
 assert.equal(title('Stock filter','statistics').panel,'products-stock');
 assert.ok(title('Your connected apps','integrations').guards.includes('settings.owner_access'));
});
