export type SectionResult = {key:string;label:string;description:string;href:string;keywords:string;reload:boolean};

export function findSections(items:SectionResult[], query:string):SectionResult[] {
  const normalize=(text:string)=>text.normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase();
  const terms=normalize(query).trim().split(/\s+/).filter(Boolean);
  if(!terms.length) return [];
  return items.filter(item=>terms.every(term=>normalize(`${item.label} ${item.description} ${item.keywords}`).includes(term))).slice(0,8);
}
