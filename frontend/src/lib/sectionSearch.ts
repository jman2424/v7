export type SectionResult = {key:string;label:string;description:string;href:string;keywords:string;reload:boolean};

export function findSections(items:SectionResult[], query:string):SectionResult[] {
  const normalize=(text:string)=>text.normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase();
  const terms=normalize(query).trim().split(/\s+/).filter(Boolean);
  if(!terms.length){
    const shortcuts=['profile','whatsapp-qr','statistics','website','conversations','pipeline'];
    return shortcuts.flatMap(key=>items.filter(item=>item.key===key));
  }
  const score=(item:SectionResult)=>{
    const label=normalize(item.label);
    const keywords=normalize(item.keywords);
    return terms.reduce((total,term)=>total+Number(label.includes(term))*2+Number(keywords.includes(term)),0);
  };
  return items
    .filter(item=>terms.every(term=>normalize(`${item.label} ${item.description} ${item.keywords}`).includes(term)))
    .sort((left,right)=>score(right)-score(left));
}
