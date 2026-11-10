"""Delivery guidance over the shared business brain; never permission grants."""
from __future__ import annotations
import re
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
        'campaign': ('owner-reviewed marketing email draft',
                     'Write the plain-text campaign body for the business owner to review. '
                     'Use the brief as direction and rely on saved public business evidence for every claim. '
                     'Use short paragraphs and a suitable call to action. Include full conditions for any offer. '
                     'Leave out subject lines, audience details, URLs, and unsubscribe instructions. '
                     'Flag missing business facts instead of inventing prices, claims, dates or terms.'),
    }
    name, guidance = profiles.get(channel, profiles['web'])
    return {'role': name, 'guidance': guidance}


_LINK = re.compile(r'https?://|mailto:|tel:', re.I)
_MATERIAL_NUMBER = re.compile(r'[£$€%]|\b\d+(?:[.,]\d+)?\s*(?:GBP|USD|EUR|pounds?|dollars?|euros?)\b', re.I)
_INVALID_SPEECH = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')
_REVIEW_INTENTS = {'book', 'quote', 'checkout', 'handoff', 'cancel', 'complaint'}


def navigation_targets(runtime, tenant):
    """Resolve the current public targets used by every delivery surface."""
    from service.platform_offer_knowledge import public_destinations
    from service.website_destinations import public_targets

    targets = public_targets(runtime.website_destinations, runtime.website_knowledge,
                             runtime.business_profile.get('website', ''))
    return targets + public_destinations(tenant, runtime.website_destinations)


def render_queued_reply(result, channel, load_targets, *, phone_page_prompt=None):
    """Adapt an accepted business reply for email or speech without granting actions."""
    if not isinstance(result, dict):
        raise ValueError('channel_invalid_answer')
    answer = result.get('reply')
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 6000 or '\x00' in answer:
        raise ValueError('channel_invalid_answer')
    agent = result.get('agent') or {}
    if not isinstance(agent, dict):
        raise ValueError('channel_invalid_agent')
    verified = result.get('_validated_channel_answer') is True
    selection = agent.get('navigation_ids')
    selected = [key for key in selection if isinstance(key, str)] if isinstance(selection, list) else []
    if verified and (channel == 'email' or selected or _LINK.search(answer)):
        from service.website_destinations import buttonize_reply

        targets = load_targets()
        answer, inline = buttonize_reply(answer, targets)
        if _LINK.search(answer):
            raise ValueError('channel_unapproved_link')
        approved = {row['id']: row for row in targets if row.get('enabled', True)}
        by_url = {row['url']: row for row in approved.values()}
        inline_urls = [row['url'] for row in inline if row.get('type') == 'navigate' and row.get('url') in by_url]
        urls = list(dict.fromkeys(inline_urls + [approved[key]['url'] for key in selected if key in approved]))[:3]
        if channel == 'email' and urls:
            answer += '\n\n' + '\n'.join(f"{by_url[url]['label']}: {url}" for url in urls)
        elif channel == 'phone' and phone_page_prompt:
            labels = [by_url[url]['label'] for url in urls
                      if url not in inline_urls and by_url[url]['label'].casefold() not in answer.casefold()]
            if labels:
                answer += '\n\n' + phone_page_prompt.format(pages=', '.join(labels))
    elif _LINK.search(answer):
        raise ValueError('channel_unapproved_link')
    if channel == 'phone':
        if _LINK.search(answer):
            raise ValueError('channel_unapproved_link')
        if _INVALID_SPEECH.search(answer):
            raise ValueError('channel_invalid_answer')
        answer = _speech_text(answer)
    if len(answer) > 6000:
        raise ValueError('channel_answer_too_long')
    local_conversation = (result.get('intent') in {'greeting', 'smalltalk', 'out_of_scope'}
                          and not _MATERIAL_NUMBER.search(answer))
    routine = ((verified or local_conversation) and agent.get('intent') not in _REVIEW_INTENTS
               and not agent.get('requested_action')
               and agent.get('next_action') not in {'open_request_form', 'request_handoff'})
    return answer, routine


def _speech_text(text):
    lines = []
    for line in text.splitlines():
        line = re.sub(r'^\s*(?:[-*•]|\d{1,2}[.)])\s+', '', line)
        line = re.sub(r'\*\*([^*\n]+)\*\*|\x60([^\x60\n]+)\x60', r'\1\2', line).strip()
        if line:
            lines.append(line if line[-1] in '.!?;:؟' else line + '.')
    return ' '.join(lines)


def draft_campaign(container, tenant, brief):
    """Use the tenant's existing retrieval, grounding and accounted completion."""
    from service.api_usage import usage_context
    from service.business_read_cache import snapshot
    from service.tenant_access import activation

    if not activation(tenant)['active']:
        return None
    with snapshot(container.storage, tenant), usage_context(tenant, 'campaign', 'v7'):
        runtime = container.for_tenant(tenant).handler.h_v7.request_copy()
        result = runtime._grounded_answer(brief, {}, channel='campaign')
    agent = result.get('agent') if isinstance(result, dict) else None
    if not isinstance(agent, dict) or agent.get('_validated_grounded') is not True:
        return None
    body = result.get('reply')
    if not isinstance(body, str) or not body.strip() or len(body) > 6000 or _LINK.search(body):
        return None
    return body.strip()


def append_message_links(text: str, targets: list[dict[str, Any]], selected: Any) -> str:
    """Messaging has no widget action tray. Resolve IDs against current targets."""
    from service.ai_disclosure import message_reply
    if not isinstance(selected, list) or any(not isinstance(key, str) for key in selected):
        return text
    approved = {row['id']: row for row in targets if row.get('enabled', True)}
    links: list[tuple[str, str]] = []
    for key in dict.fromkeys(selected):
        target = approved.get(key)
        if target and target['url'] not in text and target['url'] not in [row[1] for row in links]:
            candidate = [*links, (target['label'], target['url'])]
            body = text+'\n\n'+'\n'.join(label+': '+url for label, url in candidate)
            # Respect Twilio's supported body size, including our AI notice.
            # Never shorten verified facts or split a send into partial effects.
            if len(message_reply(body)) <= 1600:
                links = candidate
        if len(links) == 3:
            break
    return text + ('\n\n'+'\n'.join(label+': '+url for label, url in links) if links else '')
