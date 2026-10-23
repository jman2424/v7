from types import SimpleNamespace

import pytest

from handlers.handler_v7 import MessageHandlerV7
from retrieval.faq_store import FAQStore
from service.vehicle_consultation import missing_model_question


RULE={'q':'Can you classify a car from the brand alone?',
      'a':'We need the exact model before choosing a size-band estimate.',
      'tags':['vehicle_make:MINI','vehicle_make:BMW','vehicle_make:Toyota','Countryman','SUV']}


@pytest.mark.parametrize('make',['MINI','BMW','Toyota'])
def test_make_only_question_uses_explicit_tenant_rule_without_guessing_prices(make):
    answer=missing_model_question(f'I drive a {make} and want coating. Which size band and price?',[RULE])
    assert answer and f'Which {make} model' in answer and not any(c in answer for c in '£$€')


@pytest.mark.parametrize('question',[
    'I drive a MINI Countryman and want glass coating. Which size band and price?',
    'I have a BMW X5. What does coating cost?',
    'I have a Toyota Yaris Cross SUV. Which size band and price?',
    'I drive a MINI and want your opening hours.',
    'I have a MINI and need a refund. What price applies?',
    'What size band does an SUV use?',
    'I drive a Countryman and want glass coating. Which size band and price?',
])
def test_complete_models_and_unrelated_questions_continue_normally(question):
    assert missing_model_question(question,[RULE]) is None


def test_rule_must_be_explicit_current_public_tenant_knowledge():
    question='I drive a MINI and want glass coating. Which size band and price?'
    assert missing_model_question(question,[]) is None
    assert missing_model_question(question,[{**RULE,'public':False}]) is None
    assert missing_model_question(question,[{**RULE,'active':False}]) is None
    assert missing_model_question(question,[{**RULE,'q':'What are your opening hours?'}]) is None
    assert missing_model_question('hello',lambda:pytest.fail('Small talk needs no FAQ retrieval')) is None


def test_clarification_happens_before_provider_and_does_not_restart_qualification(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    handler=MessageHandlerV7(SimpleNamespace(faq=FAQStore(faq=[RULE])))
    monkeypatch.setattr(handler,'_grounded_answer',lambda *a,**k:pytest.fail('No model call needed for missing detail'))
    result=handler.handle('I drive a MINI and want glass coating. Which size band and price?',SimpleNamespace(channel='test'),{})
    assert result['intent']=='vehicle_model_clarify' and result['reply'].startswith('Which MINI model')
    from service.sales_agent import SalesAgentPolicy
    policy=SalesAgentPolicy(overrides={'sales_playbook':{'qualification_questions':["What is your car's make and model?"]}})
    final=policy.guide(result,user_text='I drive a MINI',session={})
    assert final['reply']==result['reply']
