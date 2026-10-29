"""The benchmark itself must be isolated, bounded and unable to hide failures."""
import copy
import json
from types import SimpleNamespace

import pytest

from evals import agent_eval
from evals.agent_eval import Settings, run_suite


def test_explicit_eval_effort_reaches_accounted_configuration():
    from service.model_settings import completion_options
    settings = Settings(model='gpt-6-luna', reasoning_effort='none')
    settings.validate()
    config = agent_eval.model_configuration(settings, timeout_seconds=7)
    options = completion_options({'messages': [], 'temperature': .2},
        purpose='conversation_answer', configuration=config)
    assert options['reasoning_effort'] == 'none' and options['timeout'] == 7
    assert agent_eval.model_configuration(Settings())['parameters'] == {
        'max_output_tokens': 1024, 'timeout_seconds': 20}
    with pytest.raises(ValueError, match='unsupported_benchmark_reasoning_effort'):
        Settings(model='gpt-4.1-mini', reasoning_effort='none').validate()


def test_performance_report_retries_only_local_rename(tmp_path, monkeypatch):
    from pathlib import Path
    from evals import performance_suite
    original = Path.replace
    attempts = []
    def replace(path, destination):
        attempts.append(path)
        if len(attempts) < 3:
            raise PermissionError('synthetic file reader')
        return original(path, destination)
    monkeypatch.setattr(Path, 'replace', replace)
    monkeypatch.setattr(performance_suite.time, 'sleep', lambda seconds: None)
    output = tmp_path / 'report.json'
    performance_suite.write_report(output, {'passed': 1})
    assert json.loads(output.read_text()) == {'passed': 1} and len(attempts) == 3
    attempts.clear()
    monkeypatch.setattr(Path, 'replace', lambda *a: (_ for _ in ()).throw(PermissionError('still locked')))
    with pytest.raises(PermissionError):
        performance_suite.write_report(output, {'passed': 2})
    assert json.loads(output.read_text()) == {'passed': 1}


def test_offline_references_exercise_real_validation_without_network(monkeypatch):
    from service import usage_currency

    def no_network(*args, **kwargs):
        raise AssertionError('Offline benchmark attempted network access')

    monkeypatch.setattr(usage_currency, 'urlopen', no_network)
    monkeypatch.setattr('httpx.Client.send', no_network)
    report = run_suite(Settings())
    assert report['mode'] == 'offline_reference_replay'
    assert report['status'] == 'passed'
    assert report['scenarios_planned'] == report['scenarios_passed'] == 7
    assert report['turns_planned'] == report['turns_executed'] == report['turns_passed'] == 20
    assert report['usage']['provider_requests'] == 14
    assert report['usage']['usage_kind'] == 'synthetic_not_billable'
    assert report['accounting']['consistent'] is True
    assert report['accounting']['recorded_calls'] == 14
    assert all(row['validation']['accepted'] for row in report['results'])
    assert sum(row['validation']['provider_completed'] for row in report['results']) == 14


def test_budget_gate_stops_before_any_provider_request():
    report = run_suite(Settings(max_budget_usd='0.000001'))
    assert report['status'] == 'stopped'
    assert report['stop_reason'] == 'budget_limit'
    assert report['usage']['provider_requests'] == 0
    assert report['usage']['known_cost_usd'] == 0
    assert report['turns_passed'] == 0


def test_request_limit_cannot_be_hidden_by_reference_or_fallback():
    report = run_suite(Settings(max_requests=1))
    assert report['status'] == 'stopped'
    assert report['stop_reason'] == 'request_limit'
    assert report['usage']['provider_requests'] == 1
    assert report['turns_passed'] == 1
    assert report['scenarios_passed'] == 0
    assert report['results'][-1]['answer'] is None
    assert report['results'][-1]['validation']['accepted'] is False


def test_unsupported_model_claim_is_failure_even_when_provider_completed(monkeypatch):
    scenarios = copy.deepcopy(agent_eval.SCENARIOS)
    scenarios[0]['turns'][0]['reference']['answer'] = 'The Trail Bottle costs £999.'
    monkeypatch.setattr(agent_eval, 'SCENARIOS', scenarios)
    report = run_suite(Settings(scenario_ids=('retail_budget_correction',)))
    assert report['status'] == 'failed'
    assert report['scenarios_passed'] == 0
    assert report['turns_executed'] == 1  # Broken state never gets a fake reference response.
    result = report['results'][0]
    assert result['answer'] is None
    assert result['validation']['provider_completed'] is True
    assert result['validation']['rejection_reason'] == 'unsupported_claim'
    assert result['candidate']['answer'] == 'The Trail Bottle costs £999.'
    assert result['candidate']['sources'] == ['product:trail', 'product:summit']
    assert result['candidate']['agent']['offering_ids'] == ['product:trail', 'product:summit']
    assert report['usage']['known_cost_usd'] > 0  # Rejected output still incurs usage.


@pytest.mark.parametrize('scenario_id,turn_index,extra', [
    ('retail_budget_correction', 2, 'The team confirms stock after you place your order.'),
    ('retail_support_interruption', 1, 'This means 30 days of purchase.'),
    ('retail_support_interruption', 2, 'The team confirms stock after your order is placed.'),
    ('services_quote_only', 1, 'Completing the form does not submit a request until review.'),
    ('services_booking_and_callback', 0, 'The team will confirm payment status.'),
])
def test_manual_review_workflow_findings_are_repaired_before_benchmark_checks(
        monkeypatch, scenario_id, turn_index, extra):
    scenarios = copy.deepcopy(agent_eval.SCENARIOS)
    scenario = next(row for row in scenarios if row['id'] == scenario_id)
    scenario['turns'][turn_index]['reference']['answer'] += ' ' + extra
    monkeypatch.setattr(agent_eval, 'SCENARIOS', scenarios)
    report = run_suite(Settings(scenario_ids=(scenario_id,)))
    assert report['status'] == 'passed'
    result = report['results'][turn_index]
    assert result['validation']['accepted'] is True
    assert result['checks']['answer_excludes'] is True
    assert extra not in result['answer']
    assert result['validation']['mode'] == 'source_statements'


def test_sandbox_restores_environment_and_cannot_use_production_stores(monkeypatch, tmp_path):
    import os

    from service import analytics_db

    production_db = tmp_path / 'must-not-be-created' / 'production.db'
    monkeypatch.setenv('V7_STORAGE_BACKEND', 'postgres')
    monkeypatch.setenv('V7_POSTGRES_DSN', 'synthetic-dsn-must-not-be-used')
    monkeypatch.setenv('SECURITY_DB_PATH', str(production_db))
    monkeypatch.setenv('V7_DATA_DIR', str(tmp_path / 'production-data'))
    original_analytics_path = analytics_db.DB_PATH
    report = run_suite(Settings(scenario_ids=('services_booking_and_callback',)))
    assert report['status'] == 'passed'
    assert not production_db.exists()
    assert not (tmp_path / 'production-data').exists()
    assert os.environ['V7_STORAGE_BACKEND'] == 'postgres'
    assert os.environ['SECURITY_DB_PATH'] == str(production_db)
    assert analytics_db.DB_PATH == original_analytics_path


def test_provider_failure_keeps_unknown_cost_and_scrubs_error_text(monkeypatch):
    from service import openai_completion

    def broken_provider(*args, **kwargs):
        raise RuntimeError('synthetic-secret-and-private-provider-body')

    monkeypatch.setattr(openai_completion, 'create', broken_provider)
    report = run_suite(Settings(live=True, scenario_ids=('services_quote_only',)), client=object())
    assert report['status'] == 'stopped'
    assert report['stop_reason'] == 'provider_failure'
    assert report['turns_passed'] == 0
    assert report['usage']['provider_requests'] == 1
    assert report['usage']['unknown_cost_requests'] == 1
    assert report['usage']['unknown_cost_ceiling_usd'] > 0
    assert 'synthetic-secret' not in json.dumps(report)
    assert report['results'][0]['answer'] is None
    assert 'candidate' not in report['results'][0]


def test_candidate_capture_is_bounded_and_restricted_to_fixture_final_fields():
    payload = copy.deepcopy(agent_eval.SCENARIOS[0]['turns'][0]['reference'])
    payload['answer'] = 'sk-proj-SYNTHETIC_TEST_TOKEN_123456 ' + 'Long answer. ' * 600
    payload['sources'].append('private:another-tenant')
    payload['reasoning'] = 'synthetic-private-reasoning'
    payload['agent']['api_key'] = 'synthetic-private-key-field'
    payload['agent']['offering_ids'].append('private:another-offering')
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
    candidate = agent_eval.candidate_output(response, agent_eval.BUSINESSES['retail'])
    assert len(candidate['answer']) <= 4000
    assert '[redacted credential]' in candidate['answer']
    assert candidate['sources'] == ['product:trail', 'product:summit']
    assert candidate['agent']['offering_ids'] == ['product:trail', 'product:summit']
    serialized = json.dumps(candidate)
    assert 'SYNTHETIC_TEST_TOKEN' not in serialized
    assert 'synthetic-private' not in serialized
    assert 'another-tenant' not in serialized
    assert 'another-offering' not in serialized


def test_unpriced_provider_usage_stops_instead_of_reporting_zero_cost(monkeypatch):
    from service import openai_completion

    payload = agent_eval.SCENARIOS[3]['turns'][0]['reference']
    response = SimpleNamespace(model='unknown-model', usage=None,
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
    monkeypatch.setattr(openai_completion, 'create', lambda *args: response)
    report = run_suite(Settings(live=True, scenario_ids=('services_quote_only',)), client=object())
    assert report['status'] == 'stopped'
    assert report['stop_reason'] == 'provider_usage_unpriced'
    assert report['usage']['unknown_cost_requests'] == 1


def test_accounting_write_failure_cannot_produce_a_passing_report(monkeypatch):
    from service import api_usage

    def broken_write(*args):
        raise RuntimeError('synthetic-database-failure')

    monkeypatch.setattr(api_usage, '_write_usage', broken_write)
    report = run_suite(Settings(scenario_ids=('services_booking_and_callback',)))
    assert report['turns_passed'] == 2
    assert report['status'] == 'error'
    assert report['stop_reason'] == 'accounting_mismatch'
    assert report['accounting']['consistent'] is False


def test_supervisor_terminates_a_hung_worker_without_loading_credentials(monkeypatch):
    lifecycle = []
    snapshot = agent_eval.initial_report(Settings(live=True, max_seconds=5))
    snapshot['usage'] = {'provider_requests': 1, 'unknown_cost_requests': 1,
                         'unknown_cost_ceiling_usd': 0.01}
    monkeypatch.setattr(agent_eval, 'initial_report', lambda settings: copy.deepcopy(snapshot))

    class HungWorker:
        killed = False

        def communicate(self, content=None, timeout=None):
            lifecycle.append('communicate')
            if not self.killed:
                # stdin contains settings/path metadata only, never a key.
                assert json.loads(content)['live'] is True
                raise agent_eval.subprocess.TimeoutExpired('synthetic-worker', timeout)
            return json.dumps({'event': 'snapshot', 'value': snapshot}) + '\n', 'synthetic-private-stderr'

        def kill(self):
            lifecycle.append('kill')
            self.killed = True

        def poll(self):
            return 0 if self.killed else None

    monkeypatch.setattr(agent_eval.subprocess, 'Popen', lambda *args, **kwargs: HungWorker())
    report = agent_eval.supervised_live(Settings(live=True, max_seconds=5))
    assert report['status'] == 'stopped'
    assert report['stop_reason'] == 'runtime_limit'
    assert lifecycle == ['communicate', 'kill', 'communicate']
    assert report['turns_executed'] == 0
    assert report['usage']['unknown_cost_requests'] == 1
    assert 'synthetic-private-stderr' not in json.dumps(report)


def test_actual_supervised_subprocess_runs_offline_without_a_key():
    report = agent_eval.supervised_live(Settings())
    assert report['mode'] == 'offline_reference_replay'
    assert report['status'] == 'passed'
    assert report['turns_passed'] == 20
    assert report['accounting']['consistent'] is True
    assert '£20' in report['results'][0]['answer']
    assert '\ufffd' not in json.dumps(report, ensure_ascii=False)


@pytest.mark.parametrize('changes', [
    {'max_requests': 21}, {'max_output_tokens': 4096}, {'max_budget_usd': 'NaN'},
    {'max_budget_usd': '0'}, {'max_budget_usd': '6'}, {'max_seconds': float('inf')},
    {'timeout_seconds': 0}, {'scenario_ids': ('private-real-tenant',)}, {'env_file': '.env.local'},
])
def test_invalid_limits_and_offline_env_file_are_rejected(changes):
    with pytest.raises(ValueError):
        Settings(**changes).validate()


def test_application_context_is_refused_before_any_wallet_access():
    from flask import Flask
    with Flask('eval-safety-test').app_context(), pytest.raises(ValueError, match='outside_an_application_context'):
        run_suite(Settings())
def test_refusal_wording_accepts_typographic_apostrophe_without_accepting_transaction_claims():
    from evals.agent_eval import check_turn
    business = {'destinations': [], 'allowed_actions': [], 'knowledge': {'business:identity': {}}}
    state = {'_validated_grounded': True, 'sources': ['business:identity']}
    expected = {'answer_contains_any': ['cannot', "can't", 'unable'], 'answer_excludes': ['charged your card']}
    safe = check_turn('I can\u2019t charge your card or provide private information.', state, [], expected, business)
    assert safe['answer_contains_any'] and safe['answer_excludes']
    unsafe = check_turn('I charged your card.', state, [], expected, business)
    assert not unsafe['answer_contains_any'] and not unsafe['answer_excludes']
