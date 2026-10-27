"""Full Flask request benchmark over temporary fictional tenant databases.

Provider mode can be live; storage is explicitly local SQLite, never a production
database. Keeps origin/token, credit, memory, retrieval and persistence code real.
"""
import copy
from dataclasses import asdict, dataclass
import json
import logging
import os
import tempfile
import time
from unittest.mock import patch
from evals.agent_eval import Settings


@dataclass(frozen=True)
class HttpSettings(Settings):
    def validate(self):
        # Fifty multi-turn conversations need a larger explicit request cap;
        # the original evaluator's twenty-call safety gate is unchanged.
        if type(self.max_requests) is not int or not 1 <= self.max_requests <= 300:
            raise ValueError('invalid_http_benchmark_request_cap')
        Settings(**{**asdict(self), 'max_requests': 20}).validate()


def seed(root, business):
    from service.business_core import empty_core
    from service.conversion_actions import DEFAULT_ACTIONS
    knowledge = business['knowledge']
    info = knowledge['business:identity']
    directory = root / 'business' / business['tenant']
    core = empty_core()
    core['industry'] = 'Fictional benchmark business'
    for key, row in knowledge.items():
        if key.startswith('offering:'):
            core['offerings'].append({'id': key.split(':', 1)[1], 'name': row['name'], 'type': 'service',
                'active': True, 'price_type': 'fixed' if 'price' in row else 'quote',
                'description': row['description'],
                **({'price': row['price'], 'currency': row['currency']} if 'price' in row else {})})
    if 'business_core' in knowledge:
        core['business_rules'] = copy.deepcopy(knowledge['business_core']['business_rules'])
    items = [{'sku': key.split(':', 1)[1], **row, 'unit': 'item'} for key, row in knowledge.items()
             if key.startswith('product:')]
    questions = {'returns': 'How do returns work?', 'stock': 'Is stock guaranteed?',
                 'quotes': 'How do quotes work?', 'cancellation': 'How can I cancel a consultation?',
                 'booking': 'Can I book and pay here?', 'requests': 'How do request forms work?'}
    faq = [{'q': questions.get(key.split(':', 1)[1], key), 'a': row['answer'],
            'tags': [key.split(':', 1)[1]]} for key, row in knowledge.items()
           if key.startswith(('policy:', 'capability:')) and 'answer' in row]
    actions = copy.deepcopy(DEFAULT_ACTIONS)
    for action in business['allowed_actions']:
        actions[action]['enabled'] = True
    documents = {'store_info.json': {'name': info['name'], 'about': info['description'], 'website': 'https://example.com'},
        'catalog.json': {'version': 1, 'currency': 'GBP', 'categories': [{'id': 'bottles', 'name': 'Bottles', 'items': items}]},
        'faq.json': faq, 'business_core.json': core, 'sales_actions.json': actions,
        'website_destinations.json': [{k: v for k, v in row.items() if k != 'offering_id'}
                                      for row in business['destinations']],
        'offers.json': [], 'branches.json': [], 'delivery.json': {},
        'overrides.json': {'sales_playbook': {'offering_type': 'services' if core['offerings'] else 'products'}},
        'synonyms.json': {}}
    for name, document in documents.items():
        (directory / name).write_text(json.dumps(document), encoding='utf-8')


def run_suite(settings, emit=None, client=None):
    from evals import agent_eval
    from app import create_app
    from service import chat_diagnostics, grounded_conversation, openai_completion, usage_wallet
    settings.validate()
    report = agent_eval.initial_report(settings)
    report['measurement_scope'] = 'Full Flask request, real local SQLite and optional live provider; excludes production DB/network/browser paint.'
    started = time.monotonic()
    recorder = None

    def publish():
        if recorder:
            report['usage'] = recorder.totals()
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        if emit:
            emit(copy.deepcopy(report))

    with tempfile.TemporaryDirectory(prefix='v7-http-eval-') as directory, agent_eval.sandbox(directory, settings) as root, \
            patch.dict(os.environ, {'V7_ASYNC_TELEMETRY': 'true', 'OPENAI_API_KEY': ''}):
        for business in agent_eval.BUSINESSES.values():
            seed(root, business)
        app = create_app({'TESTING': True, 'BUSINESS_KEY': agent_eval.BUSINESSES['retail']['tenant'],
                          'ENVIRONMENT': 'development', 'BASE_URL': 'http://localhost',
                          'SECRET_KEY': 'synthetic-benchmark-only-' * 3})
        recorder = agent_eval.Recorder(settings, publish)
        for business in agent_eval.BUSINESSES.values():
            usage_wallet.adjust(business['tenant'], 10000, 'Synthetic benchmark funding', 'eval', 'http-fixture')
            container = app.container.for_tenant(business['tenant'])
            container.rewriter._client = client
            container.rewriter._model = settings.model
        original_emit = chat_diagnostics.emit
        phases, outcomes, actual_knowledge, private_reply = [], [], {}, {}

        def observe(event, **fields):
            original_emit(event, **fields)
            if event == 'chat_phase' and 'elapsed_ms' in fields:
                phases.append({k: fields[k] for k in ('phase', 'elapsed_ms', 'outcome') if k in fields})
            if event == 'grounded_outcome':
                outcomes.append(fields.get('outcome'))

        def provider(active_client, options):
            if not recorder.calls or recorder.calls[-1]['provider_started']:
                recorder.stop_reason = 'unexpected_unbudgeted_model_call'
                raise agent_eval.EvalLimit(recorder.stop_reason)
            try:
                return recorder.create(active_client, options)
            except Exception as exc:
                import re
                code = getattr(exc, 'code', None)
                if isinstance(code, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', code):
                    recorder.calls[-1]['error_code'] = code
                raise

        def complete(active_client, *, purpose, **kwargs):
            nonlocal actual_knowledge
            actual_knowledge = json.loads(kwargs['messages'][1]['content'])['knowledge']
            if not settings.live:
                reference = copy.deepcopy(recorder.reference)
                mappings = {}
                for identifier, source in recorder.business['knowledge'].items():
                    for key, row in actual_knowledge.items():
                        if (identifier == 'business:identity' and key == 'business'
                                or isinstance(source, dict) and isinstance(row, dict)
                                and source.get('answer') and source.get('answer') == row.get('answer')):
                            mappings[identifier] = key
                reference['sources'] = [mappings.get(key, key) for key in reference['sources']]
                reference['statement_ids'] = [mappings.get(key.rsplit(':answer', 1)[0], key.rsplit(':answer', 1)[0]) + ':answer'
                                              for key in reference['statement_ids']]
                recorder.reference = reference
            return recorder.complete(active_client, purpose=purpose, **kwargs)

        # Only the completion boundary is injected. HTTP authorization, usage
        # reservations, conversation tokens, business data and writes are real.
        wrappers = []
        for business in agent_eval.BUSINESSES.values():
            handler = app.container.for_tenant(business['tenant']).handler
            original = handler.handle

            def capture(*args, _original=original, **kwargs):
                value = _original(*args, **kwargs)
                private_reply.clear()
                private_reply.update(value)
                return value

            wrappers.append(patch.object(handler, 'handle', capture))
        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(patch.object(grounded_conversation, 'tracked_completion', complete))
            stack.enter_context(patch.object(openai_completion, 'create', provider))
            stack.enter_context(patch.object(chat_diagnostics, 'emit', observe))
            for wrapper in wrappers:
                stack.enter_context(wrapper)
            for scenario in agent_eval.selected_scenarios(settings):
                business = agent_eval.BUSINESSES[scenario['business']]
                recorder.business = business
                token, rows = None, []
                browser = app.test_client()
                for index, turn in enumerate(scenario['turns'], 1):
                    recorder.reference = turn['reference']
                    before_calls = len(recorder.calls)
                    phases.clear()
                    outcomes.clear()
                    actual_knowledge = {}
                    begin = time.perf_counter()
                    response = browser.post('/chat_api', json={'tenant': business['tenant'], 'message': turn['user'],
                        'message_id': f'{scenario["id"]}-{index}', **({'conversation_token': token} if token else {})},
                        environ_overrides={'REMOTE_ADDR': '192.0.2.' + str(len(report['results']) % 200 + 1)})
                    data = response.get_json() or {}
                    duration = (time.perf_counter() - begin) * 1000
                    answer = data.get('reply')
                    state = copy.deepcopy(private_reply.get('agent') or {})
                    state['navigation_ids'] = state.get('navigation_ids') or []
                    # Direct source-driven/local turns have no provider call.
                    used_provider = len(recorder.calls) > before_calls
                    state['_validated_grounded'] = (response.status_code == 200 and not data.get('error')
                        and (not used_provider or bool(outcomes) and outcomes[-1] == 'accepted'))
                    state['_response_kind'] = 'conversation' if not state.get('sources') else 'answer'
                    known = {**business, 'knowledge': actual_knowledge or business['knowledge']}
                    # A request form is not a website navigation link. Check its
                    # permitted action separately instead of treating it as a URL.
                    actions = data.get('actions') or []
                    navigation = [row for row in actions if row.get('type') == 'navigate']
                    expected = copy.deepcopy(turn['expect'])
                    if scenario['id'] == 'customer_scope_and_recall' and index == 2:
                        expected['answer_contains_any'] = [*expected.get('answer_contains_any', []), business['knowledge']['business:identity']['name']]
                    checks = agent_eval.check_turn(answer, state, navigation, expected, known)
                    checks['permitted_forms_only'] = all(row.get('type') == 'navigate' or
                        row.get('type') in business['allowed_actions'] for row in actions)
                    row = {'scenario_id': scenario['id'], 'turn': index, 'passed': all(checks.values()),
                           'checks': checks, 'validation': {'accepted': checks['validator_accepted'],
                               'provider_completed': used_provider, 'latency_ms': round(duration, 2),
                               'rejection_reason': data.get('error') or (outcomes[-1] if outcomes and outcomes[-1] != 'accepted' else None)}, 'http_status': response.status_code,
                           'phases': list(phases), 'answer': answer, 'state': state}
                    rows.append(row)
                    report['results'].append(row)
                    report['turns_executed'] += 1
                    report['turns_passed'] += row['passed']
                    publish()
                    if recorder.stop_reason or response.status_code != 200:
                        break
                    token = data.get('conversation_token')
                finished = len(rows) == len(scenario['turns'])
                report['scenarios_completed'] += finished
                report['scenarios_passed'] += finished and all(r['passed'] for r in rows)
                if recorder.stop_reason:
                    break
        report['stop_reason'] = recorder.stop_reason
        report['status'] = ('stopped' if recorder.stop_reason else 'passed' if
                            report['scenarios_passed'] == report['scenarios_planned'] else 'failed')
        report['accounting'] = agent_eval.accounting_result(directory, recorder)
        publish()
        try:
            from service import telemetry_outbox
        except ImportError:
            pass
        else:
            telemetry_outbox.shutdown()
        # App loggers own fixture-local files. Windows requires closing those
        # handles before deleting this disposable directory.
        from pathlib import Path
        temporary_root = Path(directory).resolve()
        loggers = [logging.getLogger(), *(item for item in logging.Logger.manager.loggerDict.values()
                                         if isinstance(item, logging.Logger))]
        for logger in loggers:
            for handler in list(logger.handlers):
                filename = getattr(handler, 'baseFilename', None)
                if filename and Path(filename).resolve().is_relative_to(temporary_root):
                    logger.removeHandler(handler)
                    handler.close()
        import gc
        gc.collect()
    return report
