export type SectionResult = {key:string;label:string;description:string;href:string;keywords:string;reload:boolean};

function words(text:string):string[]{
  return text.normalize('NFKD').replace(/\p{M}/gu,'').toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu)||[];
}

export function findSections(items:SectionResult[], query:string):SectionResult[] {
  const terms=words(query);
  if(!terms.length){
    if(query.trim())return [];
    return ['profile','whatsapp-qr','statistics','website','conversations','pipeline']
      .flatMap(key=>items.filter(item=>item.key===key));
  }
  const phrase=terms.join(' ');
  const ranked=[];
  for(const item of items){
    const label=words(item.label), keywords=words(item.keywords), context=words(item.description);
    const prefix=(tokens:string[],term:string)=>tokens.some(word=>word.startsWith(term));
    let score=0;
    for(const term of terms){
      if(label.includes(term))score+=16;
      else if(prefix(label,term))score+=12;
      else if(prefix(keywords,term))score+=5;
      else if(prefix(context,term))score+=1;
      else {score=-1;break;}
    }
    if(score<0)continue;
    const title=label.join(' ');
    if(title===phrase)score+=120;
    else if(title.startsWith(phrase))score+=80;
    else if(terms.every((term,index)=>label[index]?.startsWith(term)))score+=55;
    ranked.push({item,score});
  }
  return ranked.sort((a,b)=>b.score-a.score).map(result=>result.item);
}
