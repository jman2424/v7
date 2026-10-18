"""Small, unambiguous conversation turns that do not need business retrieval.

Customer definitions are quotations, never tenant knowledge or instructions.
Only the supplied, bounded conversation is searched; no cross-session storage.
"""
import re


def unrelated_task(text):
    task = re.search(r"\b(?:write|make|create|build|generate|debug|solve|translate|help me|help.*with)\b", text, re.I)
    artifact = re.search(r'\b(?:python|javascript|typescript|hello[ ,]+world|calculator|homework|essay|poem|sql query)\b', text, re.I)
    business_question = re.search(r'\b(?:do you (?:sell|offer|support)|your (?:services?|products?|integration|api|widget|documentation))\b', text, re.I)
    return bool(task and artifact and not business_question)


def _definition(text):
    from service.grounded_conversation import _requirement
    if '?' in text or re.match(r'\s*(?:does|what|how|why|when|where|can|could)\b', text, re.I):
        return None
    match = re.fullmatch(r'\s*([\w][\w -]{0,39}?)\s*(?:=|means)\s*([^\n=]{1,80}?)\s*[.!]?\s*', text, re.I)
    if match and _requirement(text) and not re.search(
            r'\b(?:ignore|instructions?|system|developer|execute|forget|override|credentials?|secrets?|tokens?|keys?)\b|'
            r'\b(?:sk|rk|pk)_(?:live|test)_|\bwhsec_', text, re.I):
        return match[1].strip(), match[2].strip()
    return None


def reply(text, history, settings=None):
    from service.grounded_conversation import history_rows
    history = history_rows(history, settings)
    normalized = text.strip().casefold().rstrip('?! .')
    if re.fullmatch(r"(?:how(?:['’]d| did) your day go|how (?:was|is) your day|how are you|how r u|hru)", normalized):
        previous = [row['content'] for row in history if row['role'] == 'assistant']
        first = "Thanks for asking! I'm here and ready to help. How are you doing?"
        return ("Still here and ready to help—thanks for checking in!" if first in previous else first)
    definition = _definition(text)
    if definition:
        return f"Got it—you mean {definition[0]} = {definition[1]} in this conversation."
    recall = re.fullmatch(r'(?:does\s+(.+?)\s*=\s*what|what does\s+(.+?)\s+mean|what did i say\s+(.+?)\s+means)', normalized)
    if recall:
        key = next(part for part in recall.groups() if part).strip()
        for row in reversed(history):
            remembered = _definition(row['content']) if row['role'] == 'user' else None
            if remembered and remembered[0].casefold() == key:
                return f"You said {remembered[0]} = {remembered[1]}."
        if '=' in text or normalized.startswith('what did i say'):
            return f"What does {key} refer to? I don't have a meaning for it in this conversation."
    return None
