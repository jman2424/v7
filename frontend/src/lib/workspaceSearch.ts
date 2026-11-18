import type {SectionResult} from './sectionSearch';

type Row = Record<string, unknown>;
const rows = (value:unknown):Row[] => Array.isArray(value) ? value.filter(v=>v && typeof v==='object') : [];
const words = (...values:unknown[]) => values.flat().filter(v=>typeof v==='string' || typeof v==='number').join(' ');

// Fragment identifiers allow asynchronous editors to focus a result after navigation.
export function recordAnchor(section:string, id:string|number){
  if(section==='pipeline'||section==='conversations')return 'record-'+section+'-'+encodeURIComponent(String(id));
  let hash=2166136261;
  for(const char of String(id)) hash=Math.imul(hash ^ char.charCodeAt(0),16777619);
  return 'record-'+section+'-'+(hash>>>0).toString(36);
}

const sources:Record<string,string>={
  catalog:'catalog', faqs:'faq', offers:'offers', branches:'branches', team:'accounts',
  operations:'business-operations', subscription:'subscription', pipeline:'leads', conversations:'conversations', 'data-sources':'data-sources'
};

export async function loadSearchRecords(items:SectionResult[],tenant:string,apiPrefix:string,signal:AbortSignal,
  receive:(results:SectionResult[])=>void, allowCustomers:boolean, search?:string){
  const allowed=items.filter(page=>Object.hasOwn(sources,page.key) && (page.key!=='pipeline'||allowCustomers));
  const targeted=(key:string)=>key==='pipeline'||key==='conversations';
  const tasks=allowed.filter(page=>targeted(page.key)===(search!==undefined)).map(async page=>{
    const query=new URLSearchParams({tenant});
    if(search)query.set('q',search.slice(0,150));
    if(page.key==='pipeline')query.set('limit','50');
    if(page.key==='conversations')query.set('minutes','43200');
    const response=await fetch(apiPrefix+(page.key==='subscription'?'/billing/':'/admin/api/')+sources[page.key]+'?'+query,{credentials:'same-origin',cache:'no-store',signal});
    if(!response.ok)throw Error('search source unavailable');
    const data=await response.json();
    const result:SectionResult[]=[];
    const add=(id:unknown,label:unknown,...terms:unknown[])=>{
      if((typeof id!=='string'&&typeof id!=='number')||id===''||typeof label!=='string'||!label.trim())return;
      const anchor=recordAnchor(page.key,id);
      result.push({key:anchor,label:label.slice(0,150),description:page.label,keywords:words(page.label,label,...terms),
        href:page.href+'&focus='+recordAnchor('entry',id)+'#'+anchor,reload:true});
    };
    switch(page.key){
      case 'subscription':
        for(const row of rows(data.invoices))add(row.id,'Invoice '+words(row.month,row.kind),row.id,row.status,...rows(row.lines).map(line=>line.description));
        break;
      case 'operations':
        for(const row of rows(data.operations)){
          const payload=row.payload as Row|undefined;
          add(row.id,payload?.subject||row.source_address||row.channel,payload?.text,row.state,row.channel,row.reply);
        }
        break;
      case 'catalog':
        for(const group of rows(data.categories))for(const item of rows(group.items))
          add(item.sku,item.name,item.sku,item.description,item.tags,group.name);
        break;
      case 'faqs': for(const row of rows(data))add(row.q,row.q,row.a,row.tags);break;
      case 'offers': for(const row of rows(data))add(row.id,row.title,row.description,row.code);break;
      case 'branches': for(const row of rows(data))add(row.id,row.name,row.address,row.postcode,row.phone);break;
      case 'team': for(const row of rows(data.accounts))add(row.id,row.email,row.roles);break;
      case 'pipeline': for(const row of rows(data))add(row.lead_id,row.name||row.phone||row.lead_id,row.phone,row.status);break;
      case 'conversations': for(const row of rows(data.messages))add(row.id,row.text,row.channel);break;
      case 'data-sources': for(const row of rows(data.sources))add(row.id,row.label||row.host||row.kind,row.kind,row.host,row.status);break;
    }
    if(!signal.aborted)receive([...new Map(result.map(item=>[item.key,item])).values()]);
  });
  const outcomes=await Promise.allSettled(tasks);
  return outcomes.some(outcome=>outcome.status==='rejected');
}

export function focusSearchDestination(node:HTMLElement){
  for(let parent:HTMLElement|null=node;parent;parent=parent.parentElement){
    if(parent instanceof HTMLDetailsElement)parent.open=true;
  }
  if(node.tabIndex<0)node.tabIndex=-1;
  node.focus({preventScroll:true});
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  node.scrollIntoView({block:'nearest',behavior:reduced?'instant':'smooth'});
  if(!reduced){
    node.animate?.([{backgroundColor:'var(--v7-tint)'},{backgroundColor:getComputedStyle(node).backgroundColor}],
      {duration:320,easing:'ease-out'});
  }
}

// Resolve after the destination's lazy component and tenant data arrive.
export function revealSearchTarget(){
  const id=location.hash.slice(1);
  const sectionTarget=/^sec-[a-f0-9]{14}(?:\.sec-[a-f0-9]{14})*$/.test(id);
  if(!sectionTarget && !/^(?:record-|jump-)/.test(id))return;
  const targetId=id.replace(/^jump-/,'');
  const reveal=()=>{
    let node:HTMLElement|null=null;
    if(location.hash.slice(1)!==id)return true;
    if(sectionTarget){
      const parts=id.split('.');
      for(const ancestor of parts.slice(0,-1)){
        const details=document.querySelector<HTMLDetailsElement>(`details[data-workspace-section="${ancestor}"]`);
        if(details&&!details.open)details.open=true;
      }
      const matches=document.querySelectorAll<HTMLElement>(`#workspace [data-workspace-section="${parts.at(-1)}"]`);
      node=Array.from(matches).find(item=>item.getClientRects().length>0)||null;
      if(node instanceof HTMLLabelElement && node.control instanceof HTMLElement && !node.control.matches(':disabled'))node=node.control;
    } else node=document.getElementById(targetId);
    if(!node)return false;
    focusSearchDestination(node);
    return true;
  };
  if(reveal())return;
  const observer=new MutationObserver(()=>{if(reveal())cleanup();});
  const timer=setTimeout(()=>{
    cleanup();
    if(sectionTarget && location.hash.slice(1)===id){
      const notice=document.createElement('p');
      notice.setAttribute('role','status');
      notice.className='notice';
      notice.textContent='This section is currently unavailable in this workspace.';
      document.querySelector('#workspace .workspace-head')?.after(notice);
    }
  },20000);
  function cleanup(){observer.disconnect();clearTimeout(timer);}
  observer.observe(document.body,{childList:true,subtree:true});
  return cleanup;
}

export const searchTopics = [
  ['account','Business referrals','#business-referrals','referral link reward code invite'],
  ['budget','AI budget','#ai-budget','credit prepaid funds automatic recharge balance spending limits'],
  ['website','Test agent','test','preview simulate conversation chatbot'],
  ['website','Website installation','install','embed snippet iframe approved domains install'],
  ['website','Widget appearance','appearance','branding colours logo design theme'],
  ['statistics','Reply rates & trends','performance','response time volume performance'],
  ['statistics','Products, sales & stock','products','inventory revenue stock sales product interest'],
  ['statistics','Offer overview','offers','campaign promotions redemptions'],
  ['statistics','Lead activity','sales','conversion wins sales pipeline'],
  ['statistics','Response quality','quality','errors fallbacks common topics'],
  ['account','Change password','#password-heading','reset sign in credentials'],
  ['account','Authenticator','#authenticator-heading','two factor mfa 2fa recovery'],
  ['account','Sign-in providers','#provider-heading','google microsoft identity login'],
  ['account','Trusted devices','#device-heading','sessions browser security'],
  ['whatsapp-qr','WhatsApp QR code','#whatsapp-share','scan share link download poster'],
  ['phone','Phone setup','#channel-connect','connect telephone number twilio'],
  ['email','Email setup','#channel-connect','connect mailbox domain sender'],
  ['phone','Phone settings','#channel-settings','call handling routing hours'],
  ['email','Email settings','#channel-settings','approval draft reply mode'],
] as const;
