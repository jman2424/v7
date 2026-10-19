"""The expanded matrix must stay bounded and cannot count a skipped turn as passed."""
import pytest
from evals.agent_eval import Settings, run_suite, selected_scenarios


def test_all_200_reference_turns_exercise_validator_and_accounting(monkeypatch):
    monkeypatch.setattr('httpx.Client.send', lambda *a, **kw: pytest.fail('Reference replay must not call a provider'))
    report = run_suite(Settings(extended=True, max_requests=512))
    assert report['status'] == 'passed'
    assert report['scenarios_passed'] == report['scenarios_planned'] == 67
    assert report['turns_passed'] == report['turns_executed'] == report['turns_planned'] == 200
    assert report['usage']['usage_kind'] == 'synthetic_not_billable'
    assert report['accounting']['consistent'] and not report['accounting']['pending_reservations']


def test_extended_live_keeps_paid_request_cap():
    with pytest.raises(ValueError, match='max_requests'):
        Settings(extended=True, live=True, max_requests=21).validate()
    Settings(extended=True, live=True, max_requests=20, scenario_ids=('price_paraphrase_00',)).validate()
    assert len(selected_scenarios(Settings(extended=True, scenario_ids=('price_paraphrase_00',)))) == 1
    assert len(selected_scenarios(Settings())) == 7
