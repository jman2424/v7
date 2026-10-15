"""Provider output contract; authorization remains in server-side validation."""


def response_format(knowledge, destinations, allowed_actions, *, intents, stages, actions):
    def object_(properties):
        return {'type': 'object', 'properties': properties,
                'required': list(properties), 'additionalProperties': False}

    def strings(limit, *, choices=None):
        result = {'type': 'array', 'items': {'type': 'string', 'minLength': 1, 'maxLength': 180}, 'maxItems': limit}
        if choices is not None:
            if choices:
                result['items']['enum'] = list(choices)
            else:
                result['maxItems'] = 0
        return result

    offerings = [key for key in knowledge if key.startswith(('product:', 'offering:'))]
    update = object_({
        'add': strings(6), 'remove': strings(6), 'clear': {'type': 'boolean'},
        'evidence': {'type': 'string', 'minLength': 1, 'maxLength': 180},
    })
    state = object_({
        'intent': {'type': 'string', 'enum': sorted(intents)},
        'stage': {'type': 'string', 'enum': sorted(stages)},
        'next_action': {'type': 'string', 'enum': sorted(actions)},
        'offering_ids': strings(3, choices=offerings),
        'selected_offering_id': {'type': ['string', 'null'], 'enum': [None, *offerings]},
        'selection_update': {'type': 'string', 'enum': ['keep', 'select', 'clear']},
        'selection_evidence': {'type': ['string', 'null'], 'minLength': 1, 'maxLength': 180,
                               'description': 'Exact current customer excerpt for a change, otherwise null.'},
        'requirements': strings(6),
        'requirements_update': {'anyOf': [update, {'type': 'null'}],
                                'description': 'Null unless adding, replacing or clearing a stated requirement.'},
    })
    sources = strings(12, choices=list(knowledge))
    sources.update(minItems=1, description='Cite business facts used in the answer, including form/capability facts. '
                   'For a greeting, cite the available business identity as context.')
    schema = object_({
        'answer': {'type': 'string', 'maxLength': 4000},
        'kind': {'type': 'string', 'enum': ['answer', 'greeting', 'clarification', 'refusal']},
        'sources': sources,
        'navigation': strings(3, choices=[row['id'] for row in destinations]),
        'requested_action': {'type': ['string', 'null'], 'enum': [None, *allowed_actions]},
        'agent': state,
    })
    return {'type': 'json_schema', 'json_schema': {
        'name': 'grounded_business_agent', 'strict': True, 'schema': schema,
    }}
