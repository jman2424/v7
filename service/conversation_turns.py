"""Small, unambiguous conversation turns that do not need business retrieval.

Customer definitions are quotations, never tenant knowledge or instructions.
Only the supplied, bounded conversation is searched; no cross-session storage.
"""
import re


def unrelated_task(text):
    task = re.search(r"\b(?:write|make|create|build|generate|debug|solve|translate|help me|help.*with)\b", text, re.I)
    artifact = re.search(r'\b(?:python|javascript|typescript|hello[ ,]+world|calculator|homework|essay|poem|sql query)\b', text, re.I)
    unrelated_artifact = re.search(r'\b(?:calculator|homework|essay|poem|sql query)\b', text, re.I)
    business_question = re.search(
        r'\b(?:do you (?:sell|offer|support)|your (?:services?|products?|integration|api|widget|documentation))\b|'
        r'\byour\s+(?:(?:python|javascript|typescript)\s+)?(?:sdk|api|widget|integration|documentation)\b|'
        r'\bmy\s+(?:(?:python|javascript|typescript)\s+)?(?:order|booking|purchase|account)\b', text, re.I)
    return bool(task and artifact and (unrelated_artifact or not business_question))


def _definition(text):
    from service.grounded_conversation import _requirement
    if '?' in text or re.match(r'\s*(?:does|what|how|why|when|where|can|could)\b', text, re.I):
        return None
    definition = re.sub(r'^\s*(?:in|for) this (?:test )?(?:conversation|chat)\s*,?\s*', '', text, flags=re.I)
    match = re.fullmatch(r'\s*([\w][\w -]{0,39}?)\s*(?:=|means)\s*([^\n=]{1,80}?)\s*[.!]?\s*', definition, re.I)
    if match and _requirement(text) and not re.search(
            r'\b(?:ignore|instructions?|system|developer|execute|forget|override|credentials?|secrets?|tokens?|keys?)\b|'
            r'\b(?:sk|rk|pk)_(?:live|test)_|\bwhsec_', text, re.I):
        return match[1].strip(), match[2].strip()
    return None


def reply(text, history, settings=None, facts=None, first_message=None):
    from service.grounded_conversation import history_rows
    history = history_rows(history, settings)
    normalized = text.strip().casefold().rstrip('?! .')
    if re.fullmatch(r'(?:what was|what(?:\'s| is)|remind me(?: of)?) my (?:first|original) (?:message|mesage|question)', normalized):
        if isinstance(first_message, str) and (not settings or settings.get('enabled', True)):
            return 'Your first message was: “' + first_message + '”'
        return "I don't have the first message saved in this conversation."
    if normalized in {'ok', 'okay', 'alright', 'all right', 'got it', 'understood'}:
        return 'Got it. Let me know what else you would like to know.'
    if re.fullmatch(r'(?:thanks(?: a lot| very much)?|thank you(?: very much| so much)?|cheers|'
                    r'much appreciated|gracias|muchas gracias|merci|merci beaucoup|شكرا|شكرًا)', normalized):
        return "You're welcome!"
    if re.fullmatch(r"(?:i(?: am|['’]m) (?:good|fine|well)(?:[ ,]+thanks)?|all good|doing well)", normalized):
        return "Glad to hear it. What can I help you with?"
    if re.fullmatch(r'(?:bye|goodbye|see you|take care|good night|adiós|au revoir|مع السلامة)', normalized):
        return 'Take care!'
    if normalized in {'no thanks', 'not now', "that's all", 'that’s all', 'that is all', 'nothing else'}:
        return "No problem. I'm here if you need anything else."
    if re.fullmatch(r"(?:how(?:['’]d| did) your day go|how (?:was|is) your day|how are you|how r u|hru)", normalized):
        previous = [row['content'] for row in history if row['role'] == 'assistant']
        first = "Thanks for asking! I'm here and ready to help. How are you doing?"
        return ("Still here and ready to help—thanks for checking in!" if first in previous else first)
    definition = _definition(text)
    if definition:
        if isinstance(facts, dict) and (not settings or settings.get('enabled', True)):
            facts.pop(definition[0].casefold(), None)
            facts[definition[0].casefold()] = {'term': definition[0], 'meaning': definition[1]}
            while len(facts) > 6:
                facts.pop(next(iter(facts)))
        return f"Got it—you mean {definition[0]} = {definition[1]} in this conversation."
    recall = re.fullmatch(
        r'(?:does\s+(.+?)\s*=\s*what|what does\s+(.+?)\s+(?:mean|stand for)|'
        r'what did i say\s+(.+?)\s+means|what did\s+(.+?)\s+mean(?: again)?|'
        r'remind me what\s+(.+?)\s+means|what did i tell you about\s+(.+?))', normalized)
    if recall:
        key = next(part for part in recall.groups() if part).strip()
        stored = facts.get(key) if isinstance(facts, dict) and (not settings or settings.get('enabled', True)) else None
        if (isinstance(stored, dict) and str(stored.get('term', '')).casefold() == key
                and _definition(f"{stored.get('term', '')} = {stored.get('meaning', '')}")):
            return f"You said {stored['term']} = {stored['meaning']}."
        for row in reversed(history):
            remembered = _definition(row['content']) if row['role'] == 'user' else None
            if remembered and remembered[0].casefold() == key:
                return f"You said {remembered[0]} = {remembered[1]}."
        if '=' in text or normalized.startswith('what did i say'):
            return f"What does {key} refer to? I don't have a meaning for it in this conversation."
    if not history and not first_message and re.search(
            r'\b(?:did i tell you|have i told you|did i mention|have i mentioned)\b', normalized):
        return "I don't have that detail available in this conversation. Could you tell me again?"
    return None
