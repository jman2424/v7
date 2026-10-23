"""Readable plain-text replies without dropping or inventing business facts."""
from __future__ import annotations

import re


def catalogue_reply_limit(meta: dict) -> int:
    """Keep browsing manageable, including when the customer asks for everything."""
    ceiling = 5 if meta.get('scope') in {'full_store', 'full_category'} else 3
    try:
        return min(ceiling, max(1, int(meta.get('max_items') or ceiling)))
    except (TypeError, ValueError):
        return ceiling


def catalogue_reply_items(facts: dict) -> list:
    items = [item for item in (facts.get('items') or []) if isinstance(item, dict)
             and str(item.get('name') or item.get('_norm_name') or '').strip()]
    return items[:catalogue_reply_limit(facts.get('search_meta') or {})]


def readable_reply(text: str) -> str:
    """Add paragraph breaks to dense prose; leave lists, code and facts intact.

    This deliberately does not truncate replies: policy exceptions, prices and
    instructions must survive. New output is still plain text, never HTML.
    """
    text = (text or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    blocks = []
    prose = []
    fence = None

    def flush():
        if not prose:
            return
        block = '\n'.join(prose)
        prose.clear()
        # These clients render safe plain text, not Markdown. Do not expose
        # model emphasis delimiters as literal clutter; keep code spans intact.
        chunks = re.split(r'(`[^`\n]+`)', block)
        block = ''.join(chunk if index % 2 else re.sub(r'\*\*([^*\n]+)\*\*', r'\1', chunk)
                        for index, chunk in enumerate(chunks))
        # Whitespace is enforced here as well as requested from the model, so
        # narrow widgets do not run consecutive multi-line choices together.
        block = re.sub(r'(?<=\S)\n(?=(?:[-*•]|\d+[.)])\s)', '\n\n', block)
        # Legacy FAQs sometimes store several Small/Medium/Large price bands
        # in a single sentence. Separate the groups without changing a figure,
        # service label, condition, or their shared size-order heading.
        triplet = r'[£$€]\d[\d,.]*\s*/\s*[£$€]\d[\d,.]*\s*/\s*[£$€]\d[\d,.]*'
        if '\n' not in block and len(re.findall(triplet, block)) >= 2:
            block = re.sub(r'\bare +(?=[^£$€\n]{1,100}[£$€])', 'are\n\n', block, count=1)
            block = re.sub(r', +(?=(?:and +)?[^£$€\n,]{1,70}[£$€])', ',\n\n', block)
            block = re.sub(r'(?<=[\d.])\. +(?=[A-Z])', '.\n\n', block)
        if len(block) <= 320 or '\n' in block or re.match(r'\s*(?:[-*•]|\d+[.)])\s', block):
            blocks.append(block)
            return
        # Split only at sentence-ending punctuation followed by whitespace.
        # Decimal prices, email addresses and URLs therefore stay unchanged.
        sentences = re.split(r'(?<=[.!?]) +(?=\S)', block)
        paragraph = []
        paragraphs = []
        for sentence in sentences:
            paragraph.append(sentence)
            if len(paragraph) >= 2 or len(' '.join(paragraph)) >= 280:
                paragraphs.append(' '.join(paragraph))
                paragraph = []
        if paragraph:
            paragraphs.append(' '.join(paragraph))
        blocks.append('\n\n'.join(paragraphs))

    for line in text.split('\n'):
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if fence:
            blocks.append(line)
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                fence = None
            continue
        if marker:
            flush()
            fence = marker.group(1)
            blocks.append(line)
        elif not line.strip():
            flush()
            blocks.append('')
        else:
            prose.append(line.rstrip())
    flush()
    # Existing fenced blocks (including blank lines/indentation) are preserved.
    # Prose blocks get an empty line between paragraphs, without altering words.
    return '\n'.join(blocks).strip()
