"""Bounded synthetic conversations through V7's real grounded validator and ledger.

Default mode is offline reference replay. Live mode is explicit and supervised by
a separate process so a provider cannot outlive the run's wall-clock deadline.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from evals.scenarios import BUSINESSES, SCENARIOS
from evals.extended_scenarios import EXTENDED_SCENARIOS

ROOT = Path(__file__).resolve().parents[1]
NANO_USD = 1_000_000_000


class EvalLimit(RuntimeError):
    """A safe, fixed harness stop code; never a provider exception message."""


@dataclass(frozen=True)
class Settings:
    extended: bool = False
    live: bool = False
    model: str = 'gpt-4.1-mini'
    max_requests: int = 20
    max_output_tokens: int = 1024
    timeout_seconds: float = 20
    max_seconds: float = 180
    max_budget_usd: str = '0.50'
    scenario_ids: tuple[str, ...] = ()
    env_file: str | None = None

    def validate(self):
        from service.model_settings import MODELS
        if self.model not in MODELS:
            raise ValueError('unsupported_benchmark_model')
        limit = 512 if self.extended and not self.live else 20
        if type(self.max_requests) is not int or not 1 <= self.max_requests <= limit:
            raise ValueError('max_requests_must_be_1_to_20')
        if type(self.max_output_tokens) is not int or not 256 <= self.max_output_tokens <= 2048:
            raise ValueError('max_output_tokens_must_be_256_to_2048')
        if not math.isfinite(self.timeout_seconds) or not 5 <= self.timeout_seconds <= 30:
            raise ValueError('timeout_seconds_must_be_5_to_30')
        if not math.isfinite(self.max_seconds) or not 5 <= self.max_seconds <= 600:
            raise ValueError('max_seconds_must_be_5_to_600')
        try:
            budget = Decimal(self.max_budget_usd)
            if not budget.is_finite() or not Decimal('0') < budget <= Decimal('5'):
                raise ValueError
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError('max_budget_usd_must_be_positive_and_at_most_5') from None
        ids = [scenario['id'] for scenario in (SCENARIOS + EXTENDED_SCENARIOS if self.extended else SCENARIOS)]
        if len(ids) != len(set(ids)) or any(item not in ids for item in self.scenario_ids):
            raise ValueError('invalid_scenario_id')
        if self.env_file and not self.live:
            raise ValueError('env_file_requires_live_mode')


def selected_scenarios(settings):
    return [copy.deepcopy(row) for row in (SCENARIOS + EXTENDED_SCENARIOS if settings.extended else SCENARIOS)
            if not settings.scenario_ids or row['id'] in settings.scenario_ids]


def validate_fixtures(settings):
    """Keep reference payloads compatible with the provider's strict JSON schema."""
    import jsonschema

    from service.agent_response_schema import response_format
    from service.grounded_conversation import AGENT_ACTIONS, AGENT_INTENTS, AGENT_STAGES

    for scenario in selected_scenarios(settings):
        business = BUSINESSES[scenario['business']]
        schema = response_format(business['knowledge'], business['destinations'], business['allowed_actions'],
                                 intents=AGENT_INTENTS, stages=AGENT_STAGES, actions=AGENT_ACTIONS)
        for turn in scenario['turns']:
            jsonschema.validate(turn['reference'], schema['json_schema']['schema'])


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _revision():
    try:
        result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True,
                                text=True, timeout=3, check=False)
        revision = result.stdout.strip()
        return revision if re.fullmatch(r'[0-9a-f]{40}', revision) else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _working_tree_dirty():
    try:
        result = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT,
                                capture_output=True, text=True, timeout=3, check=False)
        return bool(result.stdout.strip()) if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _runtime_hashes():
    paths = ('service/grounded_conversation.py', 'service/grounded_statements.py',
             'service/chat_diagnostics.py', 'retrieval/faq_store.py', 'service/platform_offer_knowledge.py',
             'service/conversation_turns.py', 'service/customer_intent.py', 'service/website_destinations.py',
             'handlers/handler_v7.py', 'service/sales_agent.py', 'service/message_handler.py',
             'service/agent_knowledge.py', 'service/agent_response_schema.py', 'service/grounded_money.py',
             'service/model_settings.py', 'service/conversation_memory.py', 'service/openai_completion.py', 'service/api_usage.py',
             'service/usage_pricing.py', 'evals/agent_eval.py', 'evals/scenarios.py', 'evals/extended_scenarios.py')
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}


def initial_report(settings):
    from service.grounded_conversation import INSTRUCTIONS
    scenarios = selected_scenarios(settings)
    limits = asdict(settings)
    limits.pop('env_file')
    runtime = _runtime_hashes()
    return {'schema_version': 1, 'mode': 'live' if settings.live else 'offline_reference_replay',
            'model': settings.model, 'revision': _revision(),
            'working_tree_dirty': _working_tree_dirty(), 'runtime_code_sha256': _hash(runtime),
            'runtime_file_sha256': runtime,
            'fixture_sha256': _hash({'businesses': BUSINESSES, 'scenarios': scenarios}),
            'prompt_sha256': _hash(INSTRUCTIONS), 'limits': limits, 'status': 'running',
            'stop_reason': None, 'scenarios_planned': len(scenarios),
            'turns_planned': sum(len(row['turns']) for row in scenarios),
            'scenarios_completed': 0, 'scenarios_passed': 0, 'turns_executed': 0,
            'turns_passed': 0, 'results': [], 'usage': {},
            'quality_claim': ('Actual model outputs checked against deterministic criteria.' if settings.live
                              else 'Reference replay validates fixtures and guards; it does not measure model quality.')}


@contextmanager
def sandbox(directory, settings):
    """Redirect all accounting and storage before any tenant or wallet is used."""
    from flask import has_app_context
    from service import analytics_db
    if has_app_context():
        raise ValueError('benchmark_must_run_outside_an_application_context')
    root = Path(directory)
    environment = {
        'V7_STORAGE_BACKEND': 'sqlite', 'V7_DATA_DIR': str(root),
        'BUSINESS_DATA_ROOT': str(root / 'business'),
        'SECURITY_DB_PATH': str(root / 'security.db'),
        'ANALYTICS_DB_PATH': str(root / 'analytics.db'),
        'V7_USAGE_USD_GBP_RATE': '0.75', 'V7_USAGE_RATE_DATE': date.today().isoformat(),
        'V7_USAGE_MARKUP_PERCENT': '0', 'V7_MODEL_PRICING_JSON': '', 'V7_AUDIO_PRICING_JSON': '',
    }
    with patch.dict(os.environ, environment), patch.object(analytics_db, 'DB_PATH', str(root / 'analytics.db')):
        for business in BUSINESSES.values():
            target = root / 'business' / business['tenant']
            target.mkdir(parents=True)
            (target / 'ai_model.json').write_text(json.dumps({
                'model': settings.model, 'parameters': {
                    'max_output_tokens': settings.max_output_tokens, 'timeout_seconds': settings.timeout_seconds,
                },
            }), encoding='utf-8')
        yield root


def make_client(settings):
    """Only live mode reads a credential; dotenv values never become report fields."""
    if not settings.live:
        return object()
    from openai import OpenAI
    if settings.env_file:
        from dotenv import dotenv_values
        key = dotenv_values(settings.env_file, interpolate=False).get('OPENAI_API_KEY')
    else:
        key = os.getenv('OPENAI_API_KEY')
    if not isinstance(key, str) or not key.strip():
        raise ValueError('live_api_key_unavailable')
    # A production/custom base URL must not redirect these synthetic requests.
    # Do not enable SDK/transport request logging.
    for name in ('openai', 'httpx', 'httpcore'):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    return OpenAI(api_key=key, base_url='https://api.openai.com/v1', max_retries=0,
                  timeout=settings.timeout_seconds)


def check_turn(answer, state, links, expected, business):
    """Check selected facts, state and known wording regressions without a judge call."""
    checks = {'validator_accepted': bool(answer) and state.get('_validated_grounded') is True}
    text = (answer or '').casefold().replace('\u2019', "'")
    needs = '\n'.join(state.get('requirements', [])).casefold()
    approved_urls = {row['url'] for row in business['destinations']}
    checks['approved_navigation_only'] = all(row.get('url') in approved_urls for row in links)
    checks['approved_action_only'] = state.get('requested_action') in [None, *business['allowed_actions']]
    from service.grounded_statements import request_facts
    public_sources = {**business['knowledge'], **request_facts(business['allowed_actions'])}
    checks['approved_sources_only'] = (bool(state.get('sources')) or state.get('_response_kind') in {
        'conversation', 'greeting', 'clarification', 'refusal'}) and all(
        source in public_sources for source in state.get('sources', []))
    for key, value in expected.items():
        if key == 'selected':
            checks[key] = state.get('selected_offering_id') == value
        elif key == 'offering_ids_contains':
            checks[key] = all(item in state.get('offering_ids', []) for item in value)
        elif key in {'offering_ids', 'last_offering_ids', 'stage', 'next_action', 'requested_action', 'navigation_ids'}:
            checks[key] = state.get(key) == value
        elif key == 'intent_in':
            checks[key] = state.get('intent') in value
        elif key == 'answer_contains_any':
            checks[key] = any(item.casefold() in text for item in value)
        elif key == 'answer_contains_all':
            checks[key] = all(item.casefold() in text for item in value)
        elif key == 'answer_excludes':
            checks[key] = all(item.casefold() not in text for item in value)
        elif key == 'answer_no_question':
            checks[key] = '?' not in text if value else True
        elif key == 'requirements_contains':
            checks[key] = all(item.casefold() in needs for item in value)
        elif key == 'requirements_exclude':
            checks[key] = all(item.casefold() not in needs for item in value)
        elif key == 'navigation_contains':
            checks[key] = all(item in state.get('navigation_ids', []) for item in value)
        else:
            raise ValueError('unknown_fixture_check')
    return checks


def _candidate_text(value, limit):
    if not isinstance(value, str):
        return None
    value = re.sub(r'\bsk-[A-Za-z0-9_-]{8,}\b', '[redacted credential]', value)
    value = re.sub(r'(?i)\bbearer\s+[A-Za-z0-9._-]{12,}', 'Bearer [redacted credential]', value)
    return value[:limit]


def candidate_output(response, business):
    """Capture only bounded final JSON fields for the fixed synthetic businesses.

    This is benchmark output, never production diagnostics. Do not read provider
    error bodies, headers, response items, reasoning, credentials or source text.
    """
    from service.grounded_conversation import AGENT_ACTIONS, AGENT_INTENTS, AGENT_STAGES

    try:
        content = response.choices[0].message.content
        if not isinstance(content, str) or len(content) > 32768:
            return None
        payload = json.loads(content)
    except (AttributeError, IndexError, TypeError, ValueError, RecursionError):
        return None
    if not isinstance(payload, dict) or not business:
        return None
    from service.grounded_statements import request_facts, statement_catalog
    known = {**business['knowledge'], **request_facts(business['allowed_actions'])}
    offerings = {key for key in known if key.startswith(('product:', 'offering:'))}
    destinations = {row['id'] for row in business['destinations']}

    def ids(value, allowed, limit):
        return [row for row in value[:limit] if isinstance(row, str) and row in allowed] if isinstance(value, list) else []

    def strings(value):
        return [_candidate_text(row, 180) for row in value[:6] if isinstance(row, str)] if isinstance(value, list) else []

    result = {'answer': _candidate_text(payload.get('answer'), 4000),
              'kind': payload.get('kind') if payload.get('kind') in {'answer', 'greeting', 'clarification', 'refusal', 'conversation'} else None,
              'sources': ids(payload.get('sources'), known, 12),
              'statement_ids': ids(payload.get('statement_ids'), statement_catalog(known), 3),
              'navigation': ids(payload.get('navigation'), destinations, 3),
              'requested_action': payload.get('requested_action') if payload.get('requested_action') in business['allowed_actions'] else None}
    raw = payload.get('agent')
    if isinstance(raw, dict):
        state = {key: raw[key] for key, allowed in (
            ('intent', AGENT_INTENTS), ('stage', AGENT_STAGES), ('next_action', AGENT_ACTIONS),
            ('selection_update', {'keep', 'select', 'clear'})
        ) if isinstance(raw.get(key), str) and raw[key] in allowed}
        state['offering_ids'] = ids(raw.get('offering_ids'), offerings, 3)
        selected = raw.get('selected_offering_id')
        state['selected_offering_id'] = selected if isinstance(selected, str) and selected in offerings else None
        state['selection_evidence'] = _candidate_text(raw.get('selection_evidence'), 180)
        state['requirements'] = strings(raw.get('requirements'))
        update = raw.get('requirements_update')
        if isinstance(update, dict):
            state['requirements_update'] = {'add': strings(update.get('add')), 'remove': strings(update.get('remove')),
                'clear': update.get('clear') if type(update.get('clear')) is bool else None,
                'evidence': _candidate_text(update.get('evidence'), 180)}
        result['agent'] = state
    return result


class Recorder:
    def __init__(self, settings, emit):
        from service import api_usage, openai_completion
        from service.usage_pricing import snapshot
        self.settings, self.emit = settings, emit
        self.tracked, self.provider = api_usage.tracked_completion, openai_completion.create
        self.pricing = snapshot()
        self.deadline = time.monotonic() + settings.max_seconds
        self.budget_nano = int(Decimal(settings.max_budget_usd) * NANO_USD)
        self.known_nano = 0
        self.calls = []
        self.reference = None
        self.business = None
        self.last_candidate = None
        self.stop_reason = None

    def totals(self):
        unknown = [row for row in self.calls if row['provider_started'] and row.get('cost_nano_usd') is None]
        return {'price_version': self.pricing.version,
                'usage_kind': 'provider_reported' if self.settings.live else 'synthetic_not_billable',
                'provider_requests': sum(row['provider_started'] for row in self.calls),
                'input_tokens': sum(row.get('input_tokens') or 0 for row in self.calls),
                'output_tokens': sum(row.get('output_tokens') or 0 for row in self.calls),
                'known_cost_usd': self.known_nano / NANO_USD,
                'unknown_cost_requests': len(unknown),
                'unknown_cost_ceiling_usd': sum(row['ceiling_nano_usd'] for row in unknown) / NANO_USD,
                'calls': copy.deepcopy(self.calls)}

    def complete(self, client, *, purpose, **kwargs):
        from service import api_usage
        from service.model_settings import completion_options
        self.last_candidate = None
        remaining = self.deadline - time.monotonic()
        if len(self.calls) >= self.settings.max_requests:
            self.stop_reason = 'request_limit'
        elif remaining < 5:
            self.stop_reason = 'runtime_limit'
        if self.stop_reason:
            raise EvalLimit(self.stop_reason)
        configuration = {'model': self.settings.model, 'parameters': {
            'max_output_tokens': self.settings.max_output_tokens,
            'timeout_seconds': min(self.settings.timeout_seconds, remaining),
        }}
        effective = completion_options(kwargs, purpose=purpose, configuration=configuration)
        ceiling = api_usage.completion_ceiling(effective, pricing=self.pricing)
        held = sum(row['ceiling_nano_usd'] for row in self.calls if row.get('cost_nano_usd') is None)
        if ceiling is None or self.known_nano + held + ceiling > self.budget_nano:
            self.stop_reason = 'budget_limit' if ceiling is not None else 'pricing_unavailable'
            raise EvalLimit(self.stop_reason)
        call = {'index': len(self.calls) + 1, 'status': 'pending', 'provider_started': False,
                'ceiling_nano_usd': ceiling, 'cost_nano_usd': None}
        self.calls.append(call)
        self.emit()
        try:
            return self.tracked(client, purpose=purpose, **effective)
        except Exception as exc:
            if not call['provider_started']:
                call.update(status='failed_before_provider', cost_nano_usd=0)
            self.stop_reason = self.stop_reason or 'provider_or_accounting_failure'
            call['error_type'] = type(exc).__name__
            raise

    def create(self, client, options):
        from service import api_usage
        call = self.calls[-1]
        call['provider_started'] = True
        self.emit()
        started = time.monotonic()
        response = None
        try:
            if self.settings.live:
                response = self.provider(client, options)
            else:
                content = json.dumps(self.reference, ensure_ascii=False)
                response = SimpleNamespace(model=self.settings.model, service_tier='default',
                    usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=len(content.encode()) // 3 + 1,
                                          prompt_tokens_details=SimpleNamespace(cached_tokens=0)),
                    choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason='stop')])
            self.last_candidate = candidate_output(response, self.business)
            details = api_usage.completion_usage(response, options['model'], 'conversation_answer', 'completed',
                                                 pricing=self.pricing)
            call.update({key: details[key] for key in (
                'model', 'input_tokens', 'output_tokens', 'cached_tokens', 'cost_nano_usd')})
            call['status'] = 'completed'
            if details['cost_nano_usd'] is None:
                self.stop_reason = 'provider_usage_unpriced'
            else:
                self.known_nano += details['cost_nano_usd']
                if details['cost_nano_usd'] > call['ceiling_nano_usd']:
                    self.stop_reason = 'provider_cost_overrun'
            return response
        except Exception as exc:
            call.update(status='failed', error_type=type(exc).__name__)
            if api_usage.rejected_before_inference(exc):
                call['cost_nano_usd'] = 0
            self.stop_reason = 'provider_failure'
            raise
        finally:
            call['latency_ms'] = round((time.monotonic() - started) * 1000, 1)


def accounting_result(directory, recorder):
    """Do not silently accept the production recorder's swallowed write errors."""
    with closing(sqlite3.connect(str(Path(directory) / 'analytics.db'))) as database:
        exists = database.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='api_usage'").fetchone()
        count, known = database.execute('SELECT COUNT(*), COALESCE(SUM(cost_nano_usd), 0) FROM api_usage').fetchone() if exists else (0, 0)
    with closing(sqlite3.connect(str(Path(directory) / 'security.db'))) as database:
        unsettled = database.execute("SELECT COUNT(*) FROM usage_wallet_reservations WHERE status='pending'").fetchone()[0]
    expected = sum(row['provider_started'] for row in recorder.calls)
    return {'consistent': count == expected and known == recorder.known_nano and unsettled == 0,
            'recorded_calls': count, 'recorded_known_cost_usd': known / NANO_USD,
            'pending_reservations': unsettled, 'ledger': 'temporary_synthetic_sqlite'}


def run_suite(settings, emit=None, client=None):
    """Run only in a dedicated process; all persistent state lives in a temp dir."""
    from service import api_usage, grounded_conversation, openai_completion, usage_wallet
    from service.conversation_memory import bounded_history, DEFAULTS
    settings.validate()
    validate_fixtures(settings)
    report = initial_report(settings)
    recorder = None
    started = time.monotonic()

    def publish():
        if recorder:
            report['usage'] = recorder.totals()
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        if emit:
            emit(copy.deepcopy(report))

    with tempfile.TemporaryDirectory(prefix='v7-synthetic-eval-') as directory, sandbox(directory, settings):
        recorder = Recorder(settings, publish)
        own_client = client is None
        active_client = make_client(settings) if own_client else client
        try:
            # These credits exist only in the temporary SQLite ledger, never a
            # real customer wallet. Reservation/settlement code stays unchanged.
            for business in BUSINESSES.values():
                usage_wallet.adjust(business['tenant'], 10000, 'Synthetic benchmark funding',
                                    'eval-harness', 'fixture-funding-' + business['tenant'])
            with patch.object(grounded_conversation, 'tracked_completion', recorder.complete), \
                    patch.object(openai_completion, 'create', recorder.create):
                for scenario in selected_scenarios(settings):
                    business = BUSINESSES[scenario['business']]
                    recorder.business = business
                    history, previous, rows = [], {}, []
                    for index, turn in enumerate(scenario['turns'], 1):
                        state, links, diagnostics = {}, [], {}
                        recorder.reference = turn['reference']
                        with api_usage.usage_context(business['tenant'], 'test', 'v7'):
                            answer = grounded_conversation.answer(active_client, settings.model, turn['user'],
                                business['knowledge'], history, 'clear and helpful',
                                destinations=business['destinations'], selected_links=links,
                                agent_context={'previous_agent': previous,
                                               'offering_ids': previous.get('offering_ids') or previous.get('last_offering_ids', []),
                                               'selected_offering_id': previous.get('selected_offering_id')},
                                agent_state=state, allowed_actions=business['allowed_actions'], diagnostics=diagnostics,
                                memory_settings=DEFAULTS)
                        checks = check_turn(answer, state, links, turn['expect'], business)
                        row = {'scenario_id': scenario['id'], 'turn': index, 'passed': all(checks.values()),
                               'checks': checks, 'validation': diagnostics, 'answer': answer,
                               'state': {key: state.get(key) for key in ('intent', 'stage', 'next_action',
                                   'offering_ids', 'last_offering_ids', 'selected_offering_id', 'requirements',
                                   'retired_requirements', 'requested_action', 'navigation_ids', 'sources')}}
                        if not row['passed'] and recorder.last_candidate is not None:
                            row['candidate'] = copy.deepcopy(recorder.last_candidate)
                        report['results'].append(row)
                        rows.append(row)
                        report['turns_executed'] += 1
                        report['turns_passed'] += row['passed']
                        publish()
                        if recorder.stop_reason or not answer:
                            break  # No fallback or reference answer can mask a failed live turn.
                        history.extend([{'role': 'user', 'content': turn['user']},
                                        {'role': 'assistant', 'content': answer}])
                        history = bounded_history(history, DEFAULTS)
                        previous = state
                    complete = len(rows) == len(scenario['turns'])
                    report['scenarios_completed'] += complete
                    report['scenarios_passed'] += complete and all(row['passed'] for row in rows)
                    if recorder.stop_reason:
                        break
            report['stop_reason'] = recorder.stop_reason
            report['status'] = ('stopped' if recorder.stop_reason else
                                'passed' if report['scenarios_passed'] == report['scenarios_planned'] else 'failed')
            report['accounting'] = accounting_result(directory, recorder)
            if not report['accounting']['consistent']:
                report.update(status='error', stop_reason='accounting_mismatch')
            publish()
        finally:
            if own_client and settings.live:
                active_client.close()
    return report


def _worker_main(*, live_allowed):
    def emit(kind, value):
        # Pipes can inherit a Windows legacy code page. ASCII JSON preserves
        # every currency symbol/customer language across the UTF-8 parent pipe.
        sys.stdout.write(json.dumps({'event': kind, 'value': value}, ensure_ascii=True) + '\n')
        sys.stdout.flush()

    try:
        raw = sys.stdin.read(16385)
        if len(raw) > 16384:
            raise ValueError('worker_settings_too_large')
        arguments = json.loads(raw)
        if not isinstance(arguments, dict) or arguments.get('live', False) is not live_allowed:
            raise ValueError('worker_live_gate_mismatch')
        arguments['scenario_ids'] = tuple(arguments.get('scenario_ids', []))
        settings = Settings(**arguments)
        report = run_suite(settings, emit=lambda report: emit('snapshot', report))
        emit('done', report)
        return 0 if report['status'] == 'passed' else 1
    except Exception as exc:
        # API errors may contain credentials, URLs or request bodies. Only the
        # type is reported; never stringify provider exceptions or environments.
        emit('error', type(exc).__name__)
        return 2


def supervised_live(settings):
    """The parent does not read keys; it can kill a hung child at the deadline."""
    report = initial_report(settings)
    command = [sys.executable, '-m', 'evals.agent_eval', '--internal-worker']
    if settings.live:
        command.append('--live')
    started = time.monotonic()
    worker = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
    timed_out = False
    try:
        try:
            output, _stderr = worker.communicate(json.dumps(asdict(settings)),
                timeout=max(0.001, settings.max_seconds - (time.monotonic() - started)))
        except subprocess.TimeoutExpired:
            timed_out = True
            worker.kill()
            output, _stderr = worker.communicate(timeout=3)
        done = False
        for line in output.splitlines():
            try:
                message = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(message, dict):
                continue
            kind, value = message.get('event'), message.get('value')
            if kind in {'snapshot', 'done'} and isinstance(value, dict) and value.get('schema_version') == 1:
                report = value
                done = kind == 'done'
            elif kind == 'error' and isinstance(value, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,80}', value):
                report.update(status='error', stop_reason='worker_failed', error_type=value)
        if timed_out:
            report.update(status='stopped', stop_reason='runtime_limit')
        elif not done and report['status'] != 'error':
            report.update(status='error', stop_reason='worker_exited')
        return report
    finally:
        # Captured stderr is deliberately discarded: provider errors can include
        # private request/credential context. Reports contain only safe codes.
        if worker.poll() is None:
            worker.kill()
            worker.communicate(timeout=3)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Explicitly enable paid provider calls.')
    parser.add_argument('--extended', action='store_true', help='Include the 180-turn paraphrase and follow-up matrix; paid runs retain the 20-request cap.')
    parser.add_argument('--supervised', action='store_true', help='Exercise child-process supervision offline too.')
    parser.add_argument('--internal-worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--env-file', help='Explicit live dotenv file; only OPENAI_API_KEY is used.')
    parser.add_argument('--model', default='gpt-4.1-mini')
    parser.add_argument('--scenario', action='append', default=[], dest='scenario_ids')
    parser.add_argument('--max-requests', type=int, default=20)
    parser.add_argument('--max-output-tokens', type=int, default=1024)
    parser.add_argument('--timeout-seconds', type=float, default=20)
    parser.add_argument('--max-seconds', type=float, default=180)
    parser.add_argument('--max-budget-usd', default='0.50')
    parser.add_argument('--output', type=Path, help='Optional JSON report, preferably in ignored output/.')
    args = vars(parser.parse_args(argv))
    output = args.pop('output')
    supervised = args.pop('supervised')
    internal_worker = args.pop('internal_worker')
    if internal_worker:
        return _worker_main(live_allowed=args['live'])
    args['scenario_ids'] = tuple(args['scenario_ids'])
    settings = Settings(**args)
    try:
        settings.validate()
        if output and output.suffix.lower() != '.json':
            raise ValueError('output_must_be_a_json_file')
        report = supervised_live(settings) if settings.live or supervised else run_suite(settings)
    except Exception as exc:
        # Fixed local validation codes are safe; provider failures never reach
        # this print path as messages or reprs.
        print(json.dumps({'status': 'error', 'error_type': type(exc).__name__}))
        return 2
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = {key: report.get(key) for key in ('mode', 'status', 'stop_reason', 'model', 'revision',
        'working_tree_dirty', 'runtime_code_sha256', 'scenarios_planned', 'scenarios_passed',
        'turns_planned', 'turns_executed', 'turns_passed', 'elapsed_seconds', 'accounting')}
    summary['usage'] = {key: value for key, value in report.get('usage', {}).items() if key != 'calls'}
    if output:
        summary['report_path'] = str(output)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
