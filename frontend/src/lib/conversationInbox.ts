export type InboxMessage={id:number;ts_utc:string;channel:string;event_type:string;text:string;conversation_ref?:string|null};
export type InboxThread={key:string;channel:string;title:string;latest:InboxMessage;messages:InboxMessage[]};
export function conversationThreads(messages:InboxMessage[],channel='',search=''):InboxThread[]{
 const grouped=new Map<string,InboxThread>();
 for(const message of messages){
  if(channel&&message.channel!==channel)continue;
  // Historical records without a session must never be presented as one customer.
  const key=message.conversation_ref?message.channel+':'+message.conversation_ref:'record:'+message.id;
  let thread=grouped.get(key);
  if(!thread){thread={key,channel:message.channel,title:'Customer conversation',latest:message,messages:[]};grouped.set(key,thread);}
  thread.messages.push(message);
  if(message.id>thread.latest.id)thread.latest=message;
 }
 const query=search.trim().toLocaleLowerCase();
 return [...grouped.values()].map(thread=>{
  thread.messages.sort((a,b)=>a.id-b.id);
  thread.title=thread.messages.find(message=>message.event_type==='msg_in')?.text||'Conversation activity';
  return thread;
 }).filter(thread=>!query||thread.messages.some(message=>message.text.toLocaleLowerCase().includes(query)))
 .sort((a,b)=>b.latest.id-a.latest.id);
}
