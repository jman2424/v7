"""Respect a tenant's explicit make-only clarification policy before quoting."""
import re


def missing_model_question(question,faqs):
    if (not re.search(r'\b(?:size|band|estimates?|prices?|pricing|costs?|how much)\b',question,re.I)
            or re.search(r'\b(?:refund|cancel\w*|complain\w*|warrant\w*|privacy|account|login)\b',question,re.I)):
        return None
    intro=re.search(r"\b(?:I (?:drive|have|own)|my (?:car|vehicle) is|it['’]s|it is)\s+(?:an?\s+)?"
                    r'([^.,!?;:\n]{1,100})',question,re.I)
    if not intro:
        return None
    description=re.split(r'\b(?:and|with|for|which|that|needs?|requires?|but)\b',intro[1],maxsplit=1,flags=re.I)[0].strip()
    if not description or len(description)>40:
        return None
    rows=faqs() if callable(faqs) else faqs
    for row in rows[:120]:
        if (not isinstance(row,dict) or row.get('active') is False or row.get('public') is False
                or not re.search(r'\b(?:car|vehicle)\b',str(row.get('q','')),re.I)
                or not re.search(r'\b(?:brand|make) (?:alone|only)\b',str(row.get('q','')),re.I)
                or not re.search(r'\bexact model\b',str(row.get('a','')),re.I)):
            continue
        tags=row.get('tags',[])
        for tag in tags[:60] if isinstance(tags,list) else []:
            if not isinstance(tag,str) or not tag.startswith('vehicle_make:'):
                continue
            make=tag.split(':',1)[1].strip()
            if (len(make)<=40 and re.fullmatch(r"[^\W\d_][^\W_]*(?:[ &'’.-][^\W_]+)*",make)
                    and make.casefold()==description.casefold()):
                return (f'Which {make} model do you have? The exact model, and body style or year where '
                        'needed, lets me apply the correct size-band estimate.')
    return None
