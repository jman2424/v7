"""Progressive transport of an already validated and persisted public reply.

Never receives provider deltas. Validation, memory/CRM commits and credit
settlement finish before the first content event can be yielded.
"""
import json


def events(payload):
    text = payload['reply']
    for offset in range(0, len(text), 600):
        yield 'event: reply_chunk\ndata: ' + json.dumps({'text': text[offset:offset+600]}, ensure_ascii=True) + '\n\n'
    yield 'event: complete\ndata: ' + json.dumps(payload, ensure_ascii=True, separators=(',', ':')) + '\n\n'
