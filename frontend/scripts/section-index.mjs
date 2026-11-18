import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {parse} from 'svelte/compiler';

const virtual='virtual:v7-section-index';
const indexed=/^(?:h[1-6]|summary|legend|label|button|a|section|article|aside|nav|fieldset)$/;
const branches=['fragment','body','fallback','then','consequent','alternate'];
/** @param {unknown} value */
const componentFile=value=>typeof value==='string' && value.endsWith('.svelte') ? path.basename(value,'.svelte') : null;

/**
 * @param {any} node
 * @returns {string}
 */
function literalText(node){
  if(node?.type==='Text')return node.data;
  if(node?.type==='Literal' && typeof node.value==='string')return node.value;
  if(node?.type==='ExpressionTag')return literalText(node.expression);
  if(node?.type==='CallExpression' && node.callee.name==='$t')return literalText(node.arguments[0]);
  if(node?.type==='RegularElement' && ['b','strong','em','span'].includes(node.name))return caption(node);
  return '';
}
/**
 * @param {any} node
 * @returns {string}
 */
function caption(node){
  return (node.fragment?.nodes||[]).map(literalText).join('').replace(/\s+/g,' ').trim();
}

/** A heading or field caption supplied by a component prop or loop row.
 * @param {any} node
 */
function captionExpression(node){
  const content=node.fragment?.nodes.filter((/** @type {any} */ n)=>
    n.type==='ExpressionTag'||(n.type==='Text'&&n.data.trim()));
  if(content?.length!==1)return;
  const expr=content[0].expression;
  if(expr?.type==='Identifier'||(expr?.type==='MemberExpression'&&!expr.computed))return expr;
}

/** Static alternatives for headings whose labels depend on a selected tab.
 * @param {any} node
 * @param {Record<string,any>} values
 * @returns {string[]}
 */
function titles(node,values){
  const region=node.type==='RegularElement' && ['section','article','aside','nav','fieldset'].includes(node.name);
  if(region||node.name==='button'||node.name==='a'){
    const attr=node.attributes.find((/** @type {any} */ a)=>a.name==='aria-label');
    const label=Array.isArray(attr?.value)?attr.value.map(literalText).join('').trim():'';
    if(label)return [label];
    if(region)return [];
  }
  const resolved=known(captionExpression(node),values);
  if(typeof resolved==='string'&&resolved.trim())return [resolved];
  const fixed=caption(node);
  if(fixed)return [fixed];
  const significant=node.fragment?.nodes.filter((/** @type {any} */ n)=>n.type!=='Text'||n.data.trim())||[];
  if(significant.length!==1||significant[0].type!=='ExpressionTag')return [];
  /** @param {any} expr @returns {string[]} */
  function alternatives(expr){
    if(expr.type==='ConditionalExpression'){
      const use=known(expr.test,values);
      return [...(use===false?[]:alternatives(expr.consequent)),...(use===true?[]:alternatives(expr.alternate))];
    }
    if(expr.type==='CallExpression'&&expr.callee.name==='$t')return alternatives(expr.arguments[0]);
    return typeof expr.value==='string'?[expr.value]:[];
  }
  return [...new Set(alternatives(significant[0].expression))];
}

/** Find a panel caption without borrowing a heading from a nested panel.
 * @param {any} node
 * @param {Record<string,any>} values
 * @returns {string}
 */
function panelTitle(node,values){
  for(const child of node.fragment?.nodes||[]){
    if(child.type!=='RegularElement')continue;
    if(/^(?:h[1-6]|summary|legend)$/.test(child.name))return titles(child,values)[0]||'';
    if(child.name==='div'||child.name==='header'){
      const title=panelTitle(child,values);
      if(title)return title;
    }
  }
  return '';
}

// Resolve route and panel conditions at build time. Unknown data-dependent branches
// remain in the index. The destination always uses its normal runtime access checks.
/**
 * @param {any} node
 * @param {Record<string,any>} values
 * @returns {any}
 */
function known(node,values){
  if(!node)return;
  if(node.type==='Literal')return node.value;
  if(node.type==='Identifier')return Object.hasOwn(values,node.name)?values[node.name]:undefined;
  if(node.type==='MemberExpression'&&!node.computed){
    const object=known(node.object,values);
    return object && Object.hasOwn(object,node.property.name)?object[node.property.name]:undefined;
  }
  if(node.type==='ArrayExpression')return node.elements.map((/** @type {any} */ item)=>known(item,values));
  if(node.type==='ObjectExpression'){
    const properties=node.properties.filter((/** @type {any} */ prop)=>prop.type==='Property'&&!prop.computed);
    return Object.fromEntries(properties.map((/** @type {any} */ prop)=>[prop.key.name??prop.key.value,known(prop.value,values)]));
  }
  if(node.type==='CallExpression' && node.callee.object?.name==='Object' && node.callee.property?.name==='entries'){
    const object=known(node.arguments[0],values);
    return object && typeof object==='object'?Object.entries(object):undefined;
  }
  if(node.type==='ConditionalExpression'){
    const condition=known(node.test,values);
    if(condition!==undefined)return known(condition?node.consequent:node.alternate,values);
  }
  if(node.type==='CallExpression' && node.callee.name==='isWidgetSection')return ['test','website'].includes(values.section);
  if(node.type==='UnaryExpression' && node.operator==='!'){
    const value=known(node.argument,values);return value===undefined?undefined:!value;
  }
  const left=known(node.left,values),right=known(node.right,values);
  if(node.operator==='&&')return left===false||right===false?false:left!==undefined?(left?right:false):undefined;
  if(node.operator==='||')return left===true||right===true?true:left===false?right:undefined;
  if(left===undefined||right===undefined)return;
  if(node.operator==='===')return left===right;
  if(node.operator==='!==')return left!==right;
}

/**
 * @param {string} lib
 * @returns {import('vite').Plugin}
 */
export function sectionIndexPlugin(lib){
  const cache=new Map();
  /**
   * @param {string} name
   */
  function read(name,source=fs.readFileSync(path.join(lib,name+'.svelte'),'utf8')){
    const cached=cache.get(name);if(cached?.source===source)return cached;
    /** @type {any} */
    const ast=parse(source,{modern:true,filename:name+'.svelte'});
    const imports=new Map();
    for(const entry of ast.instance?.content.body||[]){
      const file=componentFile(entry.source?.value);
      if(file)for(const spec of entry.specifiers)imports.set(spec.local.name,file);
    }
    const anchors=new Map(),seen=new Map();
    /** @type {[number,string][]} */
    const edits=[];
    /**
     * @param {any} node
     */
    function annotate(node){
      if(!node)return;
      if(node.type==='RegularElement' && (indexed.test(node.name)||node.name==='details')){
        const expr=node.name==='details'?undefined:captionExpression(node);
        const variant=expr?source.slice(expr.start,expr.end):'';
        const title=node.name==='details'?(caption(node.fragment.nodes.find((/** @type {any} */ n)=>n.name==='summary')||{})||'disclosure'):titles(node,{}).join(' / ')||variant;
        if(title){
          const seed=name+'/'+node.name+'/'+title;
          const count=seen.get(seed)||0;seen.set(seed,count+1);
          const id='sec-'+createHash('sha256').update(seed+'/'+count).digest('hex').slice(0,14);
          anchors.set(node,{id,title,variant});
          edits.push([node.start+1+node.name.length,' data-workspace-section="'+id+'"'+(variant?' data-workspace-variant={'+variant+'}':'')]);
        }
      }
      if(node.nodes)node.nodes.forEach(annotate);
      for(const key of branches)annotate(node[key]);
    }
    annotate(ast.fragment);
    let code=source;
    for(const [pos,insert] of edits.reverse())code=code.slice(0,pos)+insert+code.slice(pos);
    const value={ast,imports,anchors,source,code};cache.set(name,value);return value;
  }
  function manifest(){
    const nav=JSON.parse(fs.readFileSync(path.resolve(lib,'../../../service/console_navigation.json'),'utf8'));
    const entries=new Map();
    cache.clear();
    for(const group of [...nav.workspaces,nav.platform])for(const route of group.views){
      const section=route.section;
      const panels=section==='website'?['appearance','test','install']:section==='statistics'?['overview','performance','products','products-sales','products-stock','offers','sales','quality']:[''];
      for(const panel of panels){
        const values={section,platformMode:group===nav.platform,widgetView:panel,messagePanel:'history'};
        /**
         * @param {string} name
         * @param {Record<string,any>} env
         * @param {boolean} active
         * @param {string[]} parents
         * @param {string[]} guards
         * @param {string[]} stack
         */
        function scan(name,env,active=false,parents=[],guards=[],stack=[]){
          if(stack.includes(name))return;
          const {ast,anchors,source,imports}=cache.get(name)||read(name);
          env={...env};
          for(const stmt of ast.instance?.content.body||[]){
            for(const decl of stmt.declarations||[]){
              if(decl.id.type==='Identifier'&&['ArrayExpression','ObjectExpression'].includes(decl.init?.type))env[decl.id.name]=known(decl.init,env);
            }
            const assign=stmt.type==='LabeledStatement'&&stmt.body?.expression;
            if(assign?.left?.type==='Identifier'&&assign.right.type==='ArrayExpression')env[assign.left.name]=known(assign.right,env);
          }
          /**
           * @param {any} node
           * @param {boolean} on
           * @param {string[]} open
           * @param {string[]} rules
           */
          function walk(node,on,open,rules,context=''){
            if(!node)return;
            if(node.type==='EachBlock'){
              const rows=known(node.expression,env);
              if(Array.isArray(rows)&&rows.length){
                const outer=env;
                for(const row of rows){
                  env={...outer};
                  if(node.context?.type==='Identifier')env[node.context.name]=row;
                  if(node.context?.type==='ArrayPattern'&&Array.isArray(row)){
                    node.context.elements.forEach((/** @type {any} */ part,/** @type {number} */ index)=>{if(part?.name)env[part.name]=row[index];});
                  }
                  walk(node.body,on,open,rules,context);
                }
                env=outer;
                walk(node.fallback,on,open,rules,context);
                return;
              }
            }
            if(node.type==='IfBlock'){
              const expr=source.slice(node.test.start,node.test.end);
              const applies=on || (name==='Console' && /\bsection\s*===|isWidgetSection\(section\)/.test(expr));
              const result=known(node.test,env);
              const guard=expr.split(/\s*&&\s*/).map((/** @type {string} */ x)=>x.trim()).filter((/** @type {string} */ x)=>['isPlatform','isOwner','canViewCosts','canViewSubscriptions','mayReadModelParameters()','mayReadConversionSettings()', "mayOpenScreen('implementation')",'settings.owner_access'].includes(x));
              if(result!==false)walk(node.consequent,applies,open,[...rules,...guard],context);
              if(result!==true)walk(node.alternate,on,open,rules,context);
              return;
            }
            const anchor=anchors.get(node);
            if(on && anchor && indexed.test(node.name)){
              for(const title of titles(node,env)){
                const key=[group.id,route.id,anchor.id,title].join('/');
                if(!entries.has(key))entries.set(key,{section,workspace:group.id,view:route.id,panel,id:anchor.id,variant:Boolean(anchor.variant),title,context:context===title?'':context,open,guards:[...new Set(rules)]});
              }
            }
            if(anchor && node.name==='details')open=[...open,anchor.id];
            if(on && node.type==='RegularElement' && ['section','article','fieldset','details'].includes(node.name)){
              context=panelTitle(node,env)||context;
            }
            const lazy=node.type==='AwaitBlock' && componentFile(node.expression?.source?.value);
            const component=node.type==='Component' && imports.get(node.name);
            if(on && (lazy||component)){
              const child={...env};
              const invocation=lazy?node.then?.nodes.find((/** @type {any} */ n)=>n.type==='SvelteComponent'):node;
              for(const attr of invocation?.attributes||[]){
                if(attr.type!=='Attribute')continue;
                const value=Array.isArray(attr.value)?attr.value[0]:attr.value;
                const resolved=value===true?true:value?.type==='Text'?value.data:known(value?.expression,env);
                if(resolved!==undefined)child[attr.name]=resolved;
              }
              if((lazy||component)==='Conversations')child.view=child.initialView||'messages';
              if((lazy||component)==='Statistics')child.view=panel.startsWith('products')?'products':panel;
              if((lazy||component)==='Implementation')child.view='install';
              if((lazy||component)==='ProductStatistics')child.view=panel.split('-')[1]||'interest';
              scan(lazy||component,child,true,open,rules,[...stack,name]);
            }
            if(node.nodes)for(const sub of node.nodes)walk(sub,on,open,rules,context);
            for(const key of branches)walk(node[key],on,open,rules,context);
          }
          walk(ast.fragment,active,parents,guards);
        }
        scan('Console',values);
      }
    }
    return [...entries.values()];
  }
  return {name:'v7-section-index',enforce:'pre',
    resolveId(id){if(id===virtual)return '\0'+virtual;},
    load(id){if(id==='\0'+virtual){
      const entries=manifest();
      this.addWatchFile(path.resolve(lib,'../../../service/console_navigation.json'));
      for(const name of cache.keys())this.addWatchFile(path.join(lib,name+'.svelte'));
      return 'export default '+JSON.stringify(entries);
    }},
    transform(source,id){
      if(!id.endsWith('.svelte')||path.resolve(path.dirname(id))!==path.resolve(lib))return;
      return {code:read(path.basename(id,'.svelte'),source).code,map:null};
    },
    handleHotUpdate(ctx){
      if(ctx.file.endsWith('.svelte')){
        const index=ctx.server.moduleGraph.getModuleById('\0'+virtual);
        if(index)return [...ctx.modules,index];
      }
    }
  };
}
