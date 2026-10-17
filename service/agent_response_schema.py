"""Provider output contract; authorization remains in server-side validation."""


def response_format(knowledge, destinations, allowed_actions, *, intents, stages, actions, statements=None):
    if statements is None:
        from service.grounded_statements import statement_catalog
        statements = statement_catalog(knowledge)
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
    update['properties']['add']['description'] = (
        'Exact contiguous excerpts from the current customer question, including connecting words. '
        'Never shorten, paraphrase or infer a requirement.')
    update['properties']['remove']['description'] = (
        'Copy exact strings from previous_agent.requirements that the current customer replaces or withdraws.')
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
    for field, description in {
        'intent': 'Classify the current request. Returns/policies use policy; a callback uses handoff even after a booking question.',
        'offering_ids': 'Only offerings discussed and cited in this answer. The previous shortlist is already in agent_context; do not repeat uncited old IDs.',
        'selected_offering_id': 'Only an explicit positive customer choice or a previous verified choice. A recommendation or stated need is not a choice.',
        'requirements': 'Copy exact contiguous customer excerpts or exact previous requirements, including connecting words. Never paraphrase; an empty array is valid.',
    }.items():
        state['properties'][field]['description'] = description
    sources = strings(12, choices=list(knowledge))
    sources.update(minItems=1, description='Cite business facts used in the answer, including form/capability facts. '
                   'For a greeting, cite the available business identity as context.')
    schema = object_({
        'answer': {'type': 'string', 'maxLength': 4000},
        'kind': {'type': 'string', 'enum': ['answer', 'greeting', 'clarification', 'refusal']},
        'sources': sources,
        'statement_ids': strings(3, choices=list(statements)),
        'navigation': strings(3, choices=[row['id'] for row in destinations]),
        'requested_action': {'type': ['string', 'null'], 'enum': [None, *allowed_actions],
                             'description': 'Null for informational pricing/process questions. Select an enabled form when the customer asks for it; callback requires agent.intent handoff.'},
        'agent': state,
    })
    schema['properties']['statement_ids']['description'] = (
        'Select complete published policy/process statement IDs from approved_statements and cite '
        'their source_ids. The server renders their full wording for protected requests. Never '
        'invent timing, conditions or team capabilities. An empty array is valid when no statement applies.')
    return {'type': 'json_schema', 'json_schema': {
        'name': 'grounded_business_agent', 'strict': True, 'schema': schema,
    }}
