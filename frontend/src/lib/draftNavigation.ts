// In-memory coordination only. Never store private form or message content here.
const readers=new Set<()=>boolean>();
let prompting=false,approvedUrl='';
export function registerDraft(reader:()=>boolean){readers.add(reader);return()=>{readers.delete(reader);};}
export function hasUnsavedDrafts(){return [...readers].some(reader=>reader());}
export function navigationApproved(url:string){return Boolean(url&&url===approvedUrl);}
export function beginDraftPrompt(){if(prompting)return false;prompting=true;return true;}
export function approveDraftNavigation(url:string){approvedUrl=url;}
export function finishDraftPrompt(){prompting=false;approvedUrl='';}
