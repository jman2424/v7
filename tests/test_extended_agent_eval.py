"""The expanded matrix must stay bounded and cannot count a skipped turn as passed."""
import pytest
from evals.agent_eval import Settings, run_suite, selected_scenarios, check_turn


def test_all_208_reference_turns_exercise_validator_and_accounting(monkeypatch):
    monkeypatch.setattr('httpx.Client.send', lambda *a, **kw: pytest.fail('Reference replay must not call a provider'))
    report = run_suite(Settings(extended=True, max_requests=512))
    assert report['status'] == 'passed'
    assert report['scenarios_passed'] == report['scenarios_planned'] == 70
    assert report['turns_passed'] == report['turns_executed'] == report['turns_planned'] == 208
    assert report['usage']['usage_kind'] == 'synthetic_not_billable'
    assert report['accounting']['consistent'] and not report['accounting']['pending_reservations']


def test_extended_live_keeps_paid_request_cap():
    with pytest.raises(ValueError, match='max_requests'):
        Settings(extended=True, live=True, max_requests=21).validate()
    Settings(extended=True, live=True, max_requests=20, scenario_ids=('price_paraphrase_00',)).validate()
    assert len(selected_scenarios(Settings(extended=True, scenario_ids=('price_paraphrase_00',)))) == 1
    assert len(selected_scenarios(Settings())) == 7


@pytest.mark.parametrize('answer,expected', [
    ("I can’t promise ten are available today. Which bottle do you mean?", True),
    ("I can't promise ten bottles are available today.", True),
    ('I can promise ten are available today.', False),
    ('Confirmed: ten are available today.', False),
])
def test_stock_wording_accepts_refusal_without_accepting_a_stock_promise(answer, expected):
    scenario = selected_scenarios(Settings(extended=True, scenario_ids=('compare_paraphrase_00',)))[0]
    from evals.scenarios import BUSINESSES
    checks = check_turn(answer, {}, [], scenario['turns'][2]['expect'], BUSINESSES['retail'])
    assert checks['answer_contains_any'] is expected
