"""Adapt the existing grounded Chat requests to the Responses API when required."""
from types import SimpleNamespace


def _field(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _input(messages):
    result = []
    for message in messages:
        if _field(message, 'type') in {'reasoning', 'function_call', 'function_call_output', 'message'}:
            # Replay opaque prior output for stateless tool turns without inspecting reasoning.
            result.append(message)
            continue
        role, content = _field(message, 'role'), _field(message, 'content')
        if role == 'tool':
            result.append({'type': 'function_call_output', 'call_id': _field(message, 'tool_call_id'),
                           'output': content})
            continue
        if role not in {'system', 'developer', 'user', 'assistant'}:
            raise ValueError('unsupported_completion_message')
        if content is not None:
            result.append({'role': role, 'content': content})
        for call in _field(message, 'tool_calls', []) or []:
            function = _field(call, 'function')
            result.append({'type': 'function_call', 'call_id': _field(call, 'id'),
                           'name': _field(function, 'name'), 'arguments': _field(function, 'arguments')})
    return result


def responses_options(options):
    options = dict(options)
    messages = options.pop('messages', [])
    result = {'model': options.pop('model'), 'input': _input(messages), 'store': False}
    result['max_output_tokens'] = options.pop('max_tokens')
    effort = options.pop('reasoning_effort', None)
    if effort is not None:
        result['reasoning'] = {'effort': effort}
    format_ = options.pop('response_format', None)
    if format_ is not None:
        if format_.get('type') == 'json_schema':
            format_ = {'type': 'json_schema', **format_['json_schema']}
        result['text'] = {'format': format_}
    tools = options.pop('tools', None)
    if tools is not None:
        result['tools'] = []
        for tool in tools:
            if tool.get('type') != 'function' or not isinstance(tool.get('function'), dict):
                raise ValueError('unsupported_completion_tool')
            result['tools'].append({'type': 'function', 'strict': False, **tool['function']})
    choice = options.pop('tool_choice', None)
    if choice is not None:
        if isinstance(choice, dict):
            if choice.get('type') != 'function':
                raise ValueError('unsupported_completion_tool_choice')
            choice = {'type': 'function', 'name': choice['function']['name']}
        result['tool_choice'] = choice
    options.pop('store', None)
    allowed = {'temperature', 'top_p', 'timeout', 'parallel_tool_calls', 'service_tier'}
    if set(options) - allowed:
        raise ValueError('unsupported_responses_option')
    return {**result, **options}


def normalize_response(response):
    """Only normalize the shape; prices and model identity use provider metadata."""
    text, calls = [], []
    for item in _field(response, 'output', []) or []:
        if _field(item, 'type') == 'message':
            for content in _field(item, 'content', []) or []:
                if _field(content, 'type') == 'output_text':
                    text.append(_field(content, 'text', ''))
        elif _field(item, 'type') == 'function_call':
            calls.append(SimpleNamespace(id=_field(item, 'call_id'), type='function', function=SimpleNamespace(
                name=_field(item, 'name'), arguments=_field(item, 'arguments'))))
    usage = _field(response, 'usage')
    normalized_usage = None if usage is None else SimpleNamespace(
        prompt_tokens=_field(usage, 'input_tokens'), completion_tokens=_field(usage, 'output_tokens'),
        prompt_tokens_details=_field(usage, 'input_tokens_details'),
    )
    return SimpleNamespace(model=_field(response, 'model'), service_tier=_field(response, 'service_tier'),
        usage=normalized_usage, choices=[SimpleNamespace(message=SimpleNamespace(
            role='assistant', content=''.join(text), tool_calls=calls or None),
            finish_reason='tool_calls' if calls else 'length' if _field(response, 'status') == 'incomplete' else 'stop')],
        # Callers that build further tool turns can retain opaque reasoning items without inspecting them.
        response_items=_field(response, 'output', []))


def create(client, options):
    from openai import OpenAI
    from service.model_settings import uses_responses
    if isinstance(client, OpenAI):
        # Bound one accounted request; retries must not multiply the configured timeout.
        client = client.with_options(max_retries=0)
    if uses_responses(options['model']):
        return normalize_response(client.responses.create(**responses_options(options)))
    return client.chat.completions.create(**{**options, 'store': False})
