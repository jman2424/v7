"""Conservative form intent shared by local routing and model-selected actions.

This decides whether to offer a customer-controlled form, never authorises a
transaction. Ambiguous follow-ups can still use the validated conversation.
"""
import re


_CLAUSES = re.compile(
    r"[,،;.!?\n]+|\b(?:but|however|instead|rather|pero|sino|mais|plutôt|لكن|بل)\b|"
    r"\band\s+(?=(?:can|could|please|i (?:want|need|would)|book|request|get|send|don['’]?t|do not)\b)", re.I)
_NEGATIVE = re.compile(
    r"\b(?:don['’]?t|do not|cannot|can['’]?t|never|not(?: to)?|no need to)\s+"
    r"(?:(?:really|actually|please)\s+)?(?:want|need|wish|plan|intend|like|"
    r"call|contact|book|schedule|arrange|request|get|send|speak|talk|chat)\b|"
    r"\b(?:no|without)\s+(?:(?:a|an|any|more|another)\s+)?"
    r"(?:demo|appointment|consultation|meeting|quote|quotation|estimate|callback|call|contact|human|person)\b|"
    r"\bnot\s+(?:interested|ready|looking)\b|\bno need(?:\s+(?:for|to))?\b|"
    r"\b(?:no thanks|not now|stop calling|stop contacting)\b|"
    r"\bno\s+(?:quiero|necesito|deseo|llames|llamen|contactes|contacten|reservar|agendar)\b|"
    r"\bsin\s+(?:cita|consulta|presupuesto|llamada)\b|"
    r"\b(?:ne|n['’])(?:\s*[\w'’]+){0,4}\s+pas\b|"
    r"\b(?:pas de|sans)\s+(?:démo|consultation|rendez-vous|devis|rappel)\b|"
    r"(?:لا|لن)\s+(?:أريد|اريد|أحتاج|احتاج|تتصل|تتصلوا|تحجز|تطلب|تتواصل)|"
    r"(?:بدون|دون)\s+(?:موعد|استشارة|اتصال|عرض سعر)", re.I)
_INFORMATION = re.compile(
    r"^(?:what|which|when|where|why|how|explain|tell me|do i need|help me understand|"
    r"can you explain|could you explain|tengo que|qué es|cómo|qu['’]est-ce|comment|هل يجب)\b|"
    r"\b(?:want|need|would like)(?:\s+to)?\s+(?:know|understand|learn|hear|find out)\b|"
    r"\b(?:information|details|questions?)\s+(?:about|on|regarding)\b|"
    r"\b(?:how much|price|cost)\b|"
    r"\b(?:not sure|not certain|still deciding|thinking about|considering|maybe|perhaps)\b|"
    r"\bif (?:i|we) (?:want|wanted|need|needed|decide|were)\b", re.I)
_FORM_TOPIC = {
    'consultation': re.compile(r'\b(?:consultation|appointment|demo|meeting|cita|consulta|rendez-vous|démo)\b|موعد|استشارة', re.I),
    'quote': re.compile(r'\b(?:quote|quotation|estimate|presupuesto|cotización|devis|estimation)\b|عرض سعر|تقدير تكلفة', re.I),
    'callback': re.compile(r'\b(?:call|callback|human|person|llámame|rappelez-moi|rappel)\b|اتصل بي', re.I),
}


def affirmative_request_text(text):
    """Retain separate affirmative clauses without altering the actual AI input."""
    return ' '.join(clause.strip() for clause in _CLAUSES.split(str(text or '').casefold())
                    if clause.strip() and not _NEGATIVE.search(clause)
                    and not _INFORMATION.search(clause.strip()))


def form_is_appropriate(text, action):
    """Do not turn a price/process question or refusal into an unsolicited form."""
    clauses = [part.strip() for part in _CLAUSES.split(str(text or '')) if part.strip()]
    affirmative = affirmative_request_text(text)
    topic = _FORM_TOPIC.get(action)
    if topic and topic.search(affirmative):
        return True
    # A short 'yes please' can refer to the previous offer. Do not invent its
    # action here; the existing model, enabled-action and state checks decide it.
    return not any(_NEGATIVE.search(part) or _INFORMATION.search(part) for part in clauses)


def explicit_form_request(text, action):
    """Recover mismatched model intent only from an affirmative customer request."""
    affirmative = affirmative_request_text(text)
    topic = _FORM_TOPIC.get(action)
    return bool(topic and topic.search(affirmative) and re.search(
        r'\b(?:book|schedule|arrange|request|need|want|get|open|prepare|provide|'
        r'work out|would like|call me|call back|reservar|agendar|solicitar|quiero|'
        r'réserver|demander|souhaite|voudrais|rappelez-moi)\b|'
        r'أريد|اريد|أحتاج|احجز|اتصل بي', affirmative, re.I))
