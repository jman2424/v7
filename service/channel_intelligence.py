"""Delivery guidance over the shared business brain; never permission grants."""
from __future__ import annotations
from typing import Any


def response_profile(channel: str) -> dict[str, str]:
    profiles = {
        'web': ('website conversation', 'Use short paragraphs and useful choices. Approved destinations appear as buttons.'),
        'test': ('website conversation test', 'Use the same knowledge and reasoning as the customer widget.'),
        'email': ('business support email',
                  'Answer every part of the current enquiry in clear plain-text paragraphs. '
                  'Keep necessary terms and prices complete; use a short list for several questions. '
                  'The server appends approved page links and the AI notice. Do not refer to chat buttons. '
                  'Use only supplied conversation context; ask one focused clarification when a previous '
                  'email or account detail is unavailable. Important requests need team review.'),
        'phone': ('spoken business conversation',
                  'Answer the current question first in natural short spoken sentences. '
                  'Ask one focused question at a time and use already stated requirements. '
                  'Avoid Markdown, visual lists, URLs and references to buttons. Name an approved page '
                  'when directing the caller. Preserve material prices, estimate qualifications and '
                  'policy conditions. Never shorten an answer by dropping required terms. '
                  'Pressing 0 takes a team message; it does not transfer the call or execute an action.'),
        'whatsapp': ('mobile business messaging',
                     'Use brief readable paragraphs and short lists for comparisons. Follow the '
                     'customer’s selected option and previous requirements. Approved page links '
                     'are added to the message; do not refer to website chat buttons or claim '
                     'that messaging identity verifies access to a private customer account.'),
    }
    name, guidance = profiles.get(channel, profiles['web'])
    return {'role': name, 'guidance': guidance}


def append_message_links(text: str, targets: list[dict[str, Any]], selected: Any) -> str:
    """Messaging has no widget action tray. Resolve IDs against current targets."""
    if not isinstance(selected, list) or any(not isinstance(key, str) for key in selected):
        return text
    approved = {row['id']: row for row in targets if row.get('enabled', True)}
    links: list[tuple[str, str]] = []
    for key in dict.fromkeys(selected):
        target = approved.get(key)
        if target and target['url'] not in text and target['url'] not in [row[1] for row in links]:
            links.append((target['label'], target['url']))
        if len(links) == 3:
            break
    return text + ('\n\n'+'\n'.join(label+': '+url for label, url in links) if links else '')
